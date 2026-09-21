from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.engine import sample_worlds, select
from backend.schemas import RunInput
from backend.store import digest

KEYS = {"observer": "test-observer", "learner": "test-learner"}
OBSERVER = {"Authorization": "Bearer test-observer"}
LEARNER = {"Authorization": "Bearer test-learner"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, KEYS)) as client:
        client.headers.update(OBSERVER)
        yield client


def workspace(client):
    project = client.get("/api/projects").json()[0]
    return client.get(f"/api/projects/{project['id']}").json()


def run_request(ws, **overrides):
    return {"policy_ids": [p["id"] for p in ws["policies"]], "worlds": 5,
            "seed": 81, "request_key": "test-request-key", **overrides}


def test_access_boundary_and_exact_binary_feedback(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    trial = client.get(f"{base}/runs/{ws['runs'][0]['id']}").json()["trials"][0]
    assert client.post("/api/session").status_code == 200
    # A learner bearer must not inherit observer privileges from a browser cookie.
    for endpoint in [base, f"{base}/export", f"{base}/runs/{ws['runs'][0]['id']}",
                     f"{base}/packages/{trial['package_id']}/review"]:
        assert client.get(endpoint, headers=LEARNER).status_code == 403
    assert client.post(f"{base}/trials/{trial['id']}/replay", headers=LEARNER).status_code == 403
    feedback = client.get(f"/api/learner/projects/{ws['project']['id']}/trials/{trial['id']}", headers=LEARNER)
    assert feedback.json() == {"passed": trial["evaluation"]["passed"]}
    public = client.get(f"/api/learner/projects/{ws['project']['id']}", headers=LEARNER).json()
    assert set(public) == {"context", "applicant_evidence", "reservation_conditions", "policies"}
    assert "reservation_conditions" not in public["context"]
    assert all(e["kind"] == "Institution" for e in public["context"]["sources"])
    assert client.get(base, headers={"Authorization": "Bearer wrong"}).status_code == 401
    client.cookies.clear()
    client.headers.clear()
    assert client.get(base).status_code == 401


def test_untrusted_origin_cannot_mutate(client):
    assert client.post("/api/session", headers={"Origin": "https://example.org"}).status_code == 403
    assert client.post("/api/session", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_matched_worlds_idempotence_and_recorded_feedback(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    request = run_request(ws)
    first = client.post(f"{base}/runs", json=request)
    assert first.status_code == 201
    assert client.post(f"{base}/runs", json=request).json() == first.json()
    detail = client.get(f"{base}/runs/{first.json()['id']}").json()
    assert len(detail["trials"]) == 15
    for i in range(5):
        trials = [t for t in detail["trials"] if t["evaluation"]["world"]["index"] == i]
        assert len({t["paired_block_id"] for t in trials}) == 1
        assert len({digest(t["evaluation"]["world"]) for t in trials}) == 1
        assert len({t["package_id"] for t in trials}) == 3
    after = client.get(base).json()
    assert len(after["runs"]) == len(ws["runs"]) + 1
    assert len(after["packages"]) == len(ws["packages"]) + 3
    assert client.post(f"{base}/runs", json={**request, "seed": 82}).status_code == 409
    assert len(client.get(base).json()["packages"]) == len(after["packages"])
    events = client.get(f"{base}/export").json()["workspace"]["events"]
    delivered = [e for e in events if e["action"] == "feedback.recorded"]
    assert len(delivered) == 36 + 15
    assert all(set(e["details"]["observation"]) == {"passed"} for e in delivered)


def test_learner_run_returns_only_handles(client):
    ws = workspace(client)
    response = client.post(f"/api/learner/projects/{ws['project']['id']}/runs",
                           json=run_request(ws), headers=LEARNER)
    assert response.status_code == 201
    assert set(response.json()) == {"run_id", "trial_ids"}
    for trial_id in response.json()["trial_ids"]:
        result = client.get(f"/api/learner/projects/{ws['project']['id']}/trials/{trial_id}", headers=LEARNER)
        assert set(result.json()) == {"passed"}


def test_versioned_edits_do_not_change_past_trials(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    old = ws["packages"][0]
    detail = client.get(f"{base}/runs/{ws['runs'][0]['id']}").json()
    revised = client.post(f"{base}/packages/{old['id']}/revisions", json={"body": "This replacement has no supporting evidence and cannot pass the reference gates."})
    assert revised.status_code == 201
    assert revised.json()["parent_id"] == old["id"]
    assert revised.json()["content_hash"] != old["content_hash"]
    client.post(f"{base}/evidence", json={"title": "New context", "kind": "Institution", "body": "The institution has changed its stated research priorities."})
    current = client.get(base).json()
    assert next(p for p in current["packages"] if p["id"] == old["id"]) == old
    for trial in detail["trials"]:
        assert client.post(f"{base}/trials/{trial['id']}/replay").json()["matches"] is True
    new_run = client.post(f"{base}/runs", json={"package_ids": [revised.json()["id"]], "worlds": 2, "request_key": "edited-document"}).json()
    trials = client.get(f"{base}/runs/{new_run['id']}").json()["trials"]
    assert all(not t["observation"]["passed"] for t in trials)


def test_deadline_is_a_gate_and_not_a_weight(client):
    ws = workspace(client)
    package = ws["packages"][0]
    deadline = datetime.fromisoformat(package["shared_context"]["deadline"]).date()
    timely = sample_worlds(42, 1, package["shared_context"], today=deadline)[0]
    late = sample_worlds(42, 1, package["shared_context"], today=deadline + timedelta(days=1))[0]
    # Remove competition to isolate the timing constraint.
    timely["rivals"] = late["rivals"] = []
    timely["minimum_score"] = late["minimum_score"] = 0
    a, b = select(package, timely), select(package, late)
    assert a["passed"] is True
    assert b["passed"] is False
    assert a["score"] == b["score"]
    assert b["gates"][0]["passed"] is False


def test_cross_project_references_rejected_and_runs_atomic(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    created = client.post("/api/projects", json={
        "name": "Other opportunity", "institution": "Other institution", "posting": "A separate opportunity with independent research requirements.",
        "deadline": "2030-01-01", "focus": ["methods"],
    }).json()
    other = f"/api/projects/{created['id']}"
    assert client.post(f"{other}/packages", json={"policy_id": ws["policies"][0]["id"]}).status_code == 404
    assert client.post(f"{other}/policies", json={"name": "Bad cross-project branch", "hypothesis": "This should be disallowed.",
                       "parents": [ws["policies"][0]["id"]], "config": {}}).status_code == 404
    failed = client.post(f"{base}/runs", json=run_request(ws, policy_ids=[ws["policies"][0]["id"], "missing-policy"]))
    assert failed.status_code == 404
    # The first draft must roll back when the second policy cannot be resolved.
    assert len(client.get(base).json()["packages"]) == len(ws["packages"])
    policy = client.post(f"{other}/policies", json={"name": "First strategy", "hypothesis": "Use evidence to support a focused proposal.", "config": {}}).json()
    assert client.post(f"{other}/runs", json={"policy_ids": [policy["id"]], "request_key": "no-evidence-run"}).status_code == 422
    assert client.get(other).json()["runs"] == []


def test_merge_preserves_both_parents(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    payload = {"name": "Combined strategy", "hypothesis": "Combine explicit alternatives with a concrete delivery plan.",
               "parents": [p["id"] for p in ws["policies"][:2]], "config": {"framing": "delivery", "plan_depth": 3, "compare_alternative": True}}
    merged = client.post(f"{base}/policies", json=payload).json()
    assert merged["parents"] == payload["parents"]
    assert merged["operation"] == "merge"
    assert merged["version"] == 2
    assert len(client.get(base).json()["policies"]) == 4


def test_seed_and_records_persist_on_restart(tmp_path):
    with TestClient(create_app(tmp_path, KEYS)) as first:
        initial = first.get("/api/projects", headers=OBSERVER).json()
        ws = first.get(f"/api/projects/{initial[0]['id']}", headers=OBSERVER).json()
    with TestClient(create_app(tmp_path, KEYS)) as second:
        assert second.get("/api/projects", headers=OBSERVER).json() == initial
        assert second.get(f"/api/projects/{initial[0]['id']}", headers=OBSERVER).json() == ws


def test_saved_package_comparison_requires_same_public_context(client):
    ws = workspace(client)
    base = f"/api/projects/{ws['project']['id']}"
    client.post(f"{base}/evidence", json={"title": "Changed priorities", "body": "New institutional priorities published after the first draft.", "kind": "Institution"})
    fresh = client.post(f"{base}/packages", json={"policy_id": ws["policies"][1]["id"]}).json()
    response = client.post(f"{base}/runs", json={"package_ids": [ws["packages"][0]["id"], fresh["id"]], "request_key": "mismatched-context"})
    assert response.status_code == 422
    assert "different public snapshots" in response.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"policy_ids": ["a"], "package_ids": ["b"]}, {"policy_ids": []},
    {"policy_ids": ["a", "a"]}, {"policy_ids": ["a"], "worlds": 0},
    {"policy_ids": ["a"], "secret_weight": 1},
])
def test_run_inputs_reject_invalid_experiments(payload):
    with pytest.raises(ValueError):
        RunInput.model_validate({"request_key": "test-validation", **payload})
