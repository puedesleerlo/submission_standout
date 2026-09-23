"""Bounded prompt-policy search with a binary-only optimizer and an observer ledger."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import random

from backend.agent_contracts import SelectionDesign, StrategyBatch, WrittenPackage, Judgment
from backend.engine import public_context, weighted
from backend.llm import ModelError
from backend.prompts import SELECTOR_DESIGNER, STRATEGIST, WRITER, JUDGE
from backend.service import ConflictError
from backend.store import digest, record_id


def frozen_worlds(design, context, seed=17):
    rng = random.Random(seed)
    today = datetime.now(timezone.utc).date().isoformat()
    worlds = []
    for index in range(12):
        scenario = rng.choices(design["scenarios"], weights=[s["probability"] for s in design["scenarios"]])[0]
        rivals = []
        for rival in design["rivals"]:
            features = {k: round(max(0, min(100, rng.gauss(v, 6))), 1) for k, v in rival["features"].items()}
            rivals.append({**rival, "features": features, "score": weighted(features, scenario["weights"]), "origin": "llm-counterfactual"})
        world = {"index": index, "scenario": scenario, "rivals": rivals, "places": scenario["places"],
                 "minimum_score": scenario["minimum_score"], "arrival_date": today, "deadline": context["deadline"],
                 "rule": scenario["rule"], "tie_break": "rivals precede candidate on exact ties", "suite_version": "kimi-selection-v1"}
        world["hash"] = digest(world)
        worlds.append(world)
    return worlds


def decide(package, judgment, world):
    """Allocation is code, not another opaque model vote. Replay uses saved judge output."""
    values = {r["dimension"]: r["score"] for r in judgment["ratings"]}
    score = weighted(values, world["scenario"]["weights"])
    rank = 1 + sum(r["score"] >= score for r in world["rivals"])
    gates = [
        {"name": "Within frozen deadline (UTC date)" if world["deadline"] else "No deadline supplied; gate not applied",
         "passed": not world["deadline"] or world["arrival_date"] <= world["deadline"]},
        {"name": "Grounded factual claims", "passed": judgment["integrity_passed"]},
        {"name": "Document meets the requested format", "passed": judgment["format_passed"]},
        {"name": "Specific, natural voice (60/100 minimum)", "passed": values["voice"] >= 60},
    ]
    if world["rule"] == "veto":
        gates.append({"name": "No criterion below 45/100", "passed": min(values.values()) >= 45})
    competitive = world["rule"] != "threshold"
    places = world["places"]
    # The frozen suite uses the initial arrival date; rolling is an explicit stress assumption.
    if world["rule"] == "rolling" and world["deadline"] and (datetime.fromisoformat(world["deadline"]) - datetime.fromisoformat(world["arrival_date"])).days <= 7:
        places = min(places, 1)
    passed = all(g["passed"] for g in gates) and score >= world["minimum_score"] and (not competitive or rank <= places)
    failed = [g["name"] for g in gates if not g["passed"]]
    reason = "Required gates failed: " + "; ".join(failed) if failed else (
        "The document did not clear this scenario's minimum score." if score < world["minimum_score"] else (
            "The document ranked outside the available places in this assumed pool." if competitive and rank > places else
            "The document met this scenario's gates and selection rule."))
    return {**judgment, "values": values, "score": score, "rank": rank, "passed": passed, "gates": gates, "reason": reason,
            "world": world, "effective_places": places, "word_count": len(package["body"].split()),
            "evaluator": "kimi-semantic-v1", "rubric_version": "kimi-personalized-v1"}


class Agents:
    def __init__(self, store, model):
        self.store, self.model = store, model
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="standout-agent")

    def status(self, conn, job):
        events = [e for e in self.store.list(conn, "agent_step", job["project_id"]) if e["job_id"] == job["id"]]
        latest = events[-1] if events else {"status": "queued", "stage": "Waiting to start"}
        return {**job, **{k: v for k, v in latest.items() if k not in {"id", "created_at", "job_id"}}, "steps": events}

    def progress(self, job, stage, status="running", **details):
        with self.store.connect(write=True) as conn:
            self.store.add(conn, "agent_step", job["project_id"], {"job_id": job["id"], "stage": stage, "status": status, **details})

    def recover(self):
        with self.store.connect(write=True) as conn:
            for job in self.store.list(conn, "agent_job"):
                if self.status(conn, job)["status"] in ("queued", "running"):
                    self.store.add(conn, "agent_step", job["project_id"], {"job_id": job["id"], "status": "failed", "stage": "Interrupted by server restart",
                        "error": "The server stopped during this round. Saved outputs remain available. Start a new round to continue."})

    def start(self, project_id, request, dispatch=True):
        with self.store.connect(write=True) as conn:
            project = self.store.get(conn, "project", project_id)
            jobs = self.store.list(conn, "agent_job", project_id)
            request_hash = digest({k: v for k, v in request.items() if k != "request_key"})
            for job in jobs:
                if job["request_key"] == request["request_key"]:
                    if job["request_hash"] != request_hash:
                        raise ConflictError("This agent request key was already used with different inputs.")
                    return self.status(conn, job)
            if any(self.status(conn, j)["status"] in ("queued", "running") for j in jobs):
                raise ConflictError("A round is already running for this project. Its progress is shown in the studio.")
            if not self.model.describe()["configured"]:
                raise ModelError("Kimi is not configured on the server.")
            evidence = self.store.list(conn, "evidence", project_id)
            facts = [e for e in evidence if e["kind"] not in ("Institution", "Idea") and e["status"] != "Hypothesis"]
            if not facts:
                raise ValueError("Add your resume, experience, or research evidence first. Kimi needs facts to write a grounded submission.")
            snapshot = public_context(project, evidence)
            models = [m for m in self.store.list(conn, "selection_model", project_id)
                      if m["context_hash"] == digest(snapshot) and m["artifact_type"] == request["artifact_type"]]
            if request["mode"] != "develop" and not models:
                raise ValueError("Develop a submission first to create a judging model for this context and document type.")
            package = None
            if request["mode"] == "evaluate":
                package = self.store.get(conn, "package", request["package_id"], project_id)
                if package["context_hash"] != digest(snapshot):
                    raise ValueError("This draft uses older public context. Develop a new submission to align the comparison.")
                if package.get("artifact_type") != request["artifact_type"]:
                    raise ValueError("Use this saved draft's original document type when evaluating it.")
            value = {**request, "project_id": project_id, "request_hash": request_hash,
                     "project_snapshot": project, "context_snapshot": snapshot, "evidence_snapshot": facts,
                     "selection_model_id": models[-1]["id"] if models and request["mode"] != "develop" else None,
                     "package_id": package["id"] if package else None, "provider": self.model.describe()["model"],
                     "max_model_calls": 1 if package else 6 if request["mode"] == "develop" else 5}
            job = self.store.add(conn, "agent_job", project_id, value)
        if dispatch:
            self.executor.submit(self.execute, job["id"], project_id)
        return {**job, "status": "queued", "stage": "Waiting to start", "steps": []}

    def learner_inputs(self, conn, job, selection_model_id):
        policies = self.store.list(conn, "policy", job["project_id"])
        # Construct this allowlist explicitly. Never serialize run/evaluation/world objects.
        visible = [{k: p[k] for k in ("id", "name", "hypothesis", "instructions", "reflection", "parents") if k in p} for p in policies if p.get("author") == "kimi"]
        runs = [r for r in self.store.list(conn, "run", job["project_id"]) if r.get("selection_model_id") == selection_model_id]
        feedback = []
        for run in runs:
            for trial_id in run["trial_ids"]:
                trial = self.store.get(conn, "trial", trial_id, job["project_id"])
                feedback.append({"policy_id": trial["policy_id"], "package_id": trial["package_id"], "passed": trial["observation"]["passed"]})
        feedback = feedback[-480:]
        counts = []
        for policy_id in dict.fromkeys(row["policy_id"] for row in feedback):
            rows = [row for row in feedback if row["policy_id"] == policy_id]
            counts.append({"policy_id": policy_id, "trials": len(rows), "passes": sum(row["passed"] for row in rows),
                           "non_passes": sum(not row["passed"] for row in rows)})
        return {"public_context": job["context_snapshot"], "applicant_evidence": job["evidence_snapshot"],
                "reservation_conditions": job["project_snapshot"]["reservation_conditions"], "artifact_type": job["artifact_type"],
                "brief": job["brief"], "available_policies": visible[-20:], "selection_feedback": feedback, "binary_counts": counts,
                "feedback_protocol": "binary-only-v1", "mode": job["mode"]}

    def execute(self, job_id, project_id):
        with self.store.connect() as conn:
            job = self.store.get(conn, "agent_job", job_id, project_id)
        try:
            model_id = job["selection_model_id"]
            if not model_id:
                self.progress(job, "Reading the opportunity and building judging scenarios")
                design, call_id = self.model.complete(project_id, job_id, "selector_designer", SELECTOR_DESIGNER,
                    {"public_context": job["context_snapshot"], "artifact_type": job["artifact_type"]}, SelectionDesign)
                with self.store.connect(write=True) as conn:
                    selector = self.store.add(conn, "selection_model", project_id, {**design,
                        "context_hash": digest(job["context_snapshot"]), "artifact_type": job["artifact_type"],
                        "worlds": frozen_worlds(design, job["context_snapshot"]), "call_id": call_id,
                        "content_hash": digest(design), "job_id": job_id, "origin": "llm-inferred-assumptions"})
                model_id = selector["id"]
            else:
                with self.store.connect() as conn:
                    selector = self.store.get(conn, "selection_model", model_id, project_id)

            packages = []
            if job["mode"] == "evaluate":
                with self.store.connect() as conn:
                    packages = [self.store.get(conn, "package", job["package_id"], project_id)]
            else:
                self.progress(job, "Designing two competing submission strategies", selection_model_id=model_id)
                with self.store.connect() as conn:
                    inputs = self.learner_inputs(conn, job, model_id)
                plans, call_id = self.model.complete(project_id, job_id, "strategist", STRATEGIST, inputs, StrategyBatch)
                allowed_evidence = {e["id"] for e in job["evidence_snapshot"]}
                allowed_parents = {p["id"] for p in inputs["available_policies"]}
                for strategy in plans["strategies"]:
                    if not set(strategy["evidence_ids"]) <= allowed_evidence or not set(strategy["parents"]) <= allowed_parents:
                        raise ModelError("Kimi referenced an unknown evidence item or strategy parent. No ungrounded draft was created.")
                    if len(set(strategy["parents"])) != len(strategy["parents"]):
                        raise ModelError("Kimi returned duplicate strategy parents.")
                    if job["mode"] == "develop" and strategy["parents"]:
                        raise ModelError("An initial strategy must start without a parent.")
                    with self.store.connect(write=True) as conn:
                        parent_versions = [self.store.get(conn, "policy", pid, project_id)["version"] for pid in strategy["parents"]]
                        policy = self.store.add(conn, "policy", project_id, {**strategy, "version": 1 + max(parent_versions, default=0),
                            "operation": "merge" if len(strategy["parents"]) == 2 else "refine" if strategy["parents"] else "explore",
                            "config": {"framing": "evidence", "evidence_limit": len(strategy["evidence_ids"]), "plan_depth": 0, "compare_alternative": False},
                            "author": "kimi", "content_hash": digest(strategy), "feedback_protocol": "binary-only-v1",
                            "learning_observation": inputs["selection_feedback"], "call_id": call_id, "job_id": job_id})
                        self.store.event(conn, project_id, "policy.registered", {"policy_id": policy["id"], "parents": policy["parents"],
                            "intervention": "llm-prompt-policy-search", "feedback_count": len(inputs["selection_feedback"])}, "strategist")
                    self.progress(job, f"Writing: {policy['name']}", selection_model_id=model_id)
                    evidence = [e for e in job["evidence_snapshot"] if e["id"] in strategy["evidence_ids"]]
                    written, writer_id = self.model.complete(project_id, job_id, "writer", WRITER, {
                        "public_context": job["context_snapshot"], "artifact_type": job["artifact_type"], "brief": job["brief"],
                        "reservation_conditions": job["project_snapshot"]["reservation_conditions"],
                        "strategy": {k: policy[k] for k in ("name", "hypothesis", "instructions", "tradeoff")}, "applicant_evidence": evidence,
                    }, WrittenPackage)
                    supplied_ids = {e["id"] for e in evidence} | {e["id"] for e in job["context_snapshot"]["sources"]}
                    if any(not set(claim["evidence_ids"]) <= supplied_ids for claim in written["claims"]):
                        raise ModelError("The draft referenced evidence it was not given. Completed work is saved; retry this round.")
                    content = {**written, "policy_id": policy["id"], "artifact_type": job["artifact_type"], "body": written["body"],
                        "evidence_snapshot": evidence, "shared_context": job["context_snapshot"], "context_hash": digest(job["context_snapshot"]),
                        "evidence_hash": digest(evidence), "constraints_snapshot": job["project_snapshot"]["reservation_conditions"],
                        "generator": "kimi-writer-v1", "parent_id": None, "human_edited": False,
                        "synthetic": job["project_snapshot"]["synthetic"], "call_id": writer_id, "job_id": job_id}
                    with self.store.connect(write=True) as conn:
                        package = self.store.add(conn, "package", project_id, {**content, "content_hash": digest(content)})
                    packages.append(package)

            judgments = []
            for package in packages:
                self.progress(job, f"Assessing: {package.get('title', 'saved draft')}", selection_model_id=model_id,
                              package_ids=[p["id"] for p in packages])
                judgment, judge_id = self.model.complete(project_id, job_id, "judge", JUDGE, {
                    "public_context": package["shared_context"], "artifact_type": package["artifact_type"],
                    "rubric": selector["rubric"], "submission": package["body"], "attached_evidence": package["evidence_snapshot"],
                }, Judgment)
                with self.store.connect(write=True) as conn:
                    assessment = self.store.add(conn, "assessment", project_id, {**judgment, "package_id": package["id"],
                        "selection_model_id": model_id, "call_id": judge_id, "job_id": job_id, "content_hash": digest(judgment)})
                judgments.append(assessment)
            self.progress(job, "Recording decisions and preserving the learner feedback boundary", selection_model_id=model_id)
            with self.store.connect(write=True) as conn:
                run_id = record_id("run")
                trial_ids = []
                for world in selector["worlds"]:
                    for package, assessment in zip(packages, judgments):
                        judgment = Judgment.model_validate({k: assessment[k] for k in Judgment.model_fields}).model_dump()
                        evaluation = decide(package, judgment, world)
                        trial = self.store.add(conn, "trial", project_id, {"run_id": run_id, "policy_id": package["policy_id"],
                            "package_id": package["id"], "observation": {"passed": evaluation["passed"]}, "evaluation": evaluation,
                            "paired_block_id": world["hash"], "package_hash": package["content_hash"], "context_hash": package["context_hash"],
                            "origin": "llm-simulation", "assessment_id": assessment["id"], "selection_model_id": model_id})
                        trial_ids.append(trial["id"])
                        self.store.event(conn, project_id, "feedback.recorded", {"trial_id": trial["id"], "observation": trial["observation"]}, "feedback-gateway")
                calls = [c for c in self.store.list(conn, "model_result", project_id) if c["job_id"] == job_id]
                result = self.store.add(conn, "run", project_id, {"project_id": project_id,
                    "policy_ids": [p["policy_id"] for p in packages], "package_ids": [p["id"] for p in packages], "trial_ids": trial_ids,
                    "world_count": len(selector["worlds"]), "seed": 17, "delay_days": 0, "context_snapshot": job["context_snapshot"],
                    "context_hash": digest(job["context_snapshot"]), "protocol": "binary-only-v1", "origin": "llm-simulation",
                    "suite_version": "kimi-selection-v1", "selection_model_id": model_id, "job_id": job_id,
                    "scenarios": selector["scenarios"], "evaluation_mode": "fixed-artifact-frozen-judge-practice-worlds",
                    "status": "completed", "intervention": "human-edited-package" if job["mode"] == "evaluate" else "llm-prompt-policy-search",
                    "cost": {"model_calls": len(calls), "model_tokens": sum(c.get("usage", {}).get("total_tokens", 0) for c in calls),
                             "external_cost_usd": None, "reference_evaluations": 0, "elapsed_ms": sum(c["elapsed_ms"] for c in calls)}}, run_id)
                self.store.event(conn, project_id, "run.completed", {"run_id": run_id, "trial_count": len(trial_ids)}, "agent-controller")
            self.progress(job, "Round complete", status="completed", run_id=result["id"], selection_model_id=model_id,
                          package_ids=[p["id"] for p in packages], policy_ids=[p["policy_id"] for p in packages], model_calls=len(calls))
        except Exception as exc:
            error = str(exc) if isinstance(exc, (ModelError, ValueError)) else "This round could not finish. Saved outputs remain available. Start another round to continue."
            self.progress(job, "Round stopped", status="failed", error=error)

    def workspace(self, conn, project_id):
        return {"jobs": [self.status(conn, j) for j in reversed(self.store.list(conn, "agent_job", project_id))],
                "selection_models": self.store.list(conn, "selection_model", project_id),
                "assessments": self.store.list(conn, "assessment", project_id), "provider": self.model.describe(),
                "packages": [p for p in self.store.list(conn, "package", project_id) if p.get("generator") == "kimi-writer-v1"],
                "policies": [p for p in self.store.list(conn, "policy", project_id) if p.get("author") == "kimi"],
                "runs": [r for r in self.store.list(conn, "run", project_id) if r.get("origin") == "llm-simulation"]}
