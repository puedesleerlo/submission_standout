import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.agent_contracts import AgentRequest, Judgment
from backend.agents import decide
from backend.llm import Moonshot, ModelError
from tests.fakes import FakeModel
from tests.test_protocol import KEYS, OBSERVER, LEARNER, workspace


@pytest.fixture
def studio(tmp_path):
    model = FakeModel()
    app = create_app(tmp_path, KEYS, model=model)
    model.store = app.state.store
    with TestClient(app) as client:
        client.headers.update(OBSERVER)
        ws = workspace(client)
        yield client, model, app.state.agents, ws


def run(agents, ws, mode="develop", **kwargs):
    request = AgentRequest(mode=mode, request_key=str(uuid.uuid4()), **kwargs).model_dump()
    job = agents.start(ws["project"]["id"], request, dispatch=False)
    agents.execute(job["id"], ws["project"]["id"])
    with agents.store.connect() as conn:
        return agents.status(conn, job)


def test_develop_iterate_is_binary_only_with_replayable_data(studio):
    client, model, agents, ws = studio
    first = run(agents, ws)
    assert first["status"] == "completed", first
    project_id = ws["project"]["id"]
    base = f"/api/projects/{project_id}"
    detail = client.get(f"{base}/runs/{first['run_id']}").json()
    assert detail["cost"]["model_calls"] == 6
    assert detail["cost"]["external_cost_usd"] is None
    assert len(detail["trials"]) == 24
    assert len(detail["summaries"][0]["by_scenario"]) == 3
    for t in detail["trials"]:
        assert client.get(f"/api/learner/projects/{project_id}/trials/{t['id']}", headers=LEARNER).json() == t["observation"]
        assert client.post(f"{base}/trials/{t['id']}/replay").json()["matches"]
    second = run(agents, ws, mode="iterate")
    assert second["status"] == "completed", second
    planner = [call for call in model.calls if call["role"] == "strategist"][-1]["inputs"]
    assert len(planner["selection_feedback"]) == 24
    assert sum(row["trials"] for row in planner["binary_counts"]) == 24
    assert all(row["passes"] + row["non_passes"] == row["trials"] for row in planner["binary_counts"])
    assert all(set(item) == {"policy_id", "package_id", "passed"} for item in planner["selection_feedback"])
    assert "SEALED_SELECTOR_SENTINEL" not in json.dumps(planner)
    assert "PRIVATE_CRITIQUE_SENTINEL" not in json.dumps(planner)
    for call in model.calls:
        if call["role"] == "writer":
            assert "SEALED_SELECTOR_SENTINEL" not in json.dumps(call["inputs"])
            assert "PRIVATE_CRITIQUE_SENTINEL" not in json.dumps(call["inputs"])
        if call["role"] == "selector_designer":
            assert set(call["inputs"]) == {"public_context", "artifact_type"}
        if call["role"] == "judge":
            assert "strategy" not in call["inputs"]
            assert "reservation_conditions" not in call["inputs"]
    next_detail = client.get(f"{base}/runs/{second['run_id']}").json()
    assert {t["paired_block_id"] for t in detail["trials"]} == {t["paired_block_id"] for t in next_detail["trials"]}
    data = client.get(f"{base}/studio").json()
    assert any(p["parents"] and p["learning_observation"] for p in data["policies"])
    assert client.get(f"{base}/studio", headers=LEARNER).status_code == 403
    assert client.get("/api/model", headers=LEARNER).status_code == 403
    export = client.get(f"{base}/export").json()
    assert len(export["model_calls"]) == 11
    assert len(export["model_results"]) == 11


def test_failed_model_is_not_negative_reward_and_completed_outputs_persist(studio):
    client, model, agents, ws = studio
    model.fail_role = "judge"
    result = run(agents, ws)
    assert result["status"] == "failed"
    data = client.get(f"/api/projects/{ws['project']['id']}/studio").json()
    assert len(data["packages"]) == 2
    assert data["runs"] == []
    assert not data["assessments"]
    assert len(client.get(f"/api/projects/{ws['project']['id']}").json()["runs"]) == 1  # original reference seed only


def test_request_deduplication_conflict_and_restart_recovery(studio):
    client, model, agents, ws = studio
    request = AgentRequest(request_key="stable-request").model_dump()
    project_id = ws["project"]["id"]
    original = agents.start(project_id, request, dispatch=False)
    assert agents.start(project_id, request, dispatch=False)["id"] == original["id"]
    assert client.post(f"/api/projects/{project_id}/agent-jobs", json={**request, "brief": "Changed"}).status_code == 409
    assert client.post(f"/api/projects/{project_id}/agent-jobs", json={**request, "request_key": "different-key"}).status_code == 409
    agents.recover()
    data = client.get(f"/api/projects/{project_id}/studio").json()
    assert data["jobs"][0]["status"] == "failed"
    assert data["jobs"][0]["stage"] == "Interrupted by server restart"
    assert not model.calls


def test_saved_edit_uses_a_fresh_judgment_and_preserves_original(studio):
    client, model, agents, ws = studio
    first = run(agents, ws)
    base = f"/api/projects/{ws['project']['id']}"
    data = client.get(f"{base}/studio").json()
    old = data["packages"][0]
    new = client.post(f"{base}/packages/{old['id']}/revisions", json={"body": old["body"] + "\n\nThe scope remains subject to a joint review."}).json()
    evaluated = run(agents, ws, mode="evaluate", package_id=new["id"])
    assert evaluated["status"] == "completed"
    assert model.calls[-1]["inputs"]["submission"] == new["body"]
    assert len(model.calls) == 7
    assert client.post(f"{base}/runs", json={"package_ids": [new["id"]], "request_key": "reference-mismatch"}).status_code == 422
    original = client.get(f"{base}/runs/{first['run_id']}").json()
    assert client.post(f"{base}/trials/{original['trials'][0]['id']}/replay").json()["matches"]


def test_new_public_context_requires_a_new_selector(studio):
    client, model, agents, ws = studio
    run(agents, ws)
    base = f"/api/projects/{ws['project']['id']}"
    client.post(f"{base}/evidence", json={"title": "Changed institutional context", "body": "The organization now prioritizes a different research outcome.", "kind": "Institution"})
    response = client.post(f"{base}/agent-jobs", json={"mode": "iterate", "request_key": "changed-context"})
    assert response.status_code == 422
    assert "judging model" in response.json()["detail"]


def test_natural_voice_cannot_be_compensated_by_other_scores(studio):
    client, model, agents, ws = studio
    first = run(agents, ws)
    detail = client.get(f"/api/projects/{ws['project']['id']}/runs/{first['run_id']}").json()
    evaluation = detail["trials"][0]["evaluation"]
    judgment = Judgment.model_validate({k: evaluation[k] for k in Judgment.model_fields}).model_dump()
    for rating in judgment["ratings"]:
        rating["score"] = 59 if rating["dimension"] == "voice" else 100
    world = {**evaluation["world"], "minimum_score": 0, "rivals": []}
    result = decide({"body": "A sample document"}, judgment, world)
    assert result["score"] > 80
    assert result["passed"] is False


def test_provider_does_not_leak_key_and_persists_calls(studio):
    client, fake, agents, ws = studio
    secret = "test-key-never-in-traces"
    def response(request):
        assert request.headers["authorization"] == "Bearer " + secret
        body = json.loads(request.content)
        assert body["model"] == "kimi-k3"
        assert body["reasoning_effort"] == "low"
        assert secret not in request.content.decode()
        # Malformed structured result must not become a trial or expose raw provider text.
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "malformed " + secret}}], "usage": {"total_tokens": 20}})
    model = Moonshot(agents.store, {"key": secret, "model": "kimi-k3", "base_url": "https://api.moonshot.ai/v1", "max_tokens": 10000,
                     "timeout_seconds": 20, "max_calls_per_day": 1}, httpx.MockTransport(response))
    with pytest.raises(ModelError, match="invalid structured"):
        model.complete(ws["project"]["id"], "fixture-job", "judge", "JSON please", {}, Judgment)
    with agents.store.connect() as conn:
        traces = agents.store.list(conn, "model_call") + agents.store.list(conn, "model_result")
    assert secret not in json.dumps(traces)
    assert traces[-1]["status"] == "failed"
    with pytest.raises(ModelError, match="daily model-call budget"):
        model.complete(ws["project"]["id"], "fixture-job", "judge", "JSON please", {}, Judgment)


def test_async_job_api_reaches_completion(studio):
    client, model, agents, ws = studio
    base = f"/api/projects/{ws['project']['id']}"
    assert client.post(f"{base}/agent-jobs", json={"request_key": "async-api-test"}, headers=LEARNER).status_code == 403
    response = client.post(f"{base}/agent-jobs", json={"request_key": "async-api-test"})
    assert response.status_code == 202
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        job = client.get(f"{base}/studio").json()["jobs"][0]
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(.03)
    assert job["status"] == "completed"


@pytest.mark.parametrize("rule,expected", [("top_k", False), ("threshold", True), ("veto", False)])
def test_selection_rules_change_allocation_under_same_score(rule, expected):
    ratings = [{"dimension": d, "score": 75, "explanation": "Adequate, grounded performance on this dimension."}
               for d in ("fit", "evidence", "feasibility", "originality", "voice")]
    judgment = {"ratings": ratings, "integrity_passed": True, "format_passed": True}
    world = {"scenario": {"weights": {r["dimension"]: .2 for r in ratings}}, "arrival_date": "2026-09-20", "deadline": "2026-12-01",
             "rivals": [{"score": 90}, {"score": 85}, {"score": 70}], "places": 2, "minimum_score": 65, "rule": rule}
    result = decide({"body": "Submitted artifact"}, judgment, world)
    assert result["score"] == 75
    assert result["rank"] == 3
    assert result["passed"] is expected


def test_rolling_capacity_is_an_explicit_frozen_timing_assumption():
    ratings = [{"dimension": d, "score": 75, "explanation": "Adequate, grounded performance on this dimension."}
               for d in ("fit", "evidence", "feasibility", "originality", "voice")]
    judgment = {"ratings": ratings, "integrity_passed": True, "format_passed": True}
    world = {"scenario": {"weights": {r["dimension"]: .2 for r in ratings}}, "arrival_date": "2026-09-20", "deadline": "2026-09-24",
             "rivals": [{"score": 90}, {"score": 70}, {"score": 60}], "places": 2, "minimum_score": 65, "rule": "top_k"}
    assert decide({"body": "Submitted artifact"}, judgment, world)["passed"] is True
    rolling = decide({"body": "Submitted artifact"}, judgment, {**world, "rule": "rolling"})
    assert rolling["passed"] is False
    assert rolling["effective_places"] == 1
