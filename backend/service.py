from datetime import date, datetime, timezone
import time

from backend.engine import SCENARIOS, compose, public_context, sample_worlds, select
from backend.store import digest, record_id


class ConflictError(Exception):
    pass


class Service:
    def __init__(self, store):
        self.store = store

    def create_project(self, conn, payload, synthetic=False):
        identity = record_id("project")
        project = self.store.add(conn, "project", identity, {**payload, "synthetic": synthetic}, identity)
        self.store.event(conn, identity, "project.created", {"project_id": identity})
        return project

    def create_policy(self, conn, project_id, payload):
        self.store.get(conn, "project", project_id)
        parents = [self.store.get(conn, "policy", pid, project_id) for pid in payload["parents"]]
        version = 1 + max([p["version"] for p in parents], default=0)
        value = {**payload, "version": version, "operation": "merge" if len(parents) == 2 else "refine" if parents else "seed",
                 "feedback_protocol": "binary-selection-v1", "author": "observer", "content_hash": digest(payload)}
        policy = self.store.add(conn, "policy", project_id, value)
        self.store.event(conn, project_id, "policy.registered", {"policy_id": policy["id"], "parents": payload["parents"], "intervention": "human-authored-policy"})
        return policy

    def draft(self, conn, project_id, policy_id):
        project = self.store.get(conn, "project", project_id)
        policy = self.store.get(conn, "policy", policy_id, project_id)
        if policy.get("author") == "kimi":
            raise ValueError("Use the submission studio to develop or revise a Kimi strategy. The reference compositor cannot execute its instructions.")
        evidence = self.store.list(conn, "evidence", project_id)
        content = compose(project, policy, evidence)
        content["content_hash"] = digest(content)
        package = self.store.add(conn, "package", project_id, content)
        self.store.event(conn, project_id, "package.generated", {"package_id": package["id"], "policy_id": policy_id}, "reference-worker")
        return package

    def run(self, conn, project_id, request, actor="observer"):
        start = time.perf_counter()
        self.store.get(conn, "project", project_id)
        request_hash = digest({k: v for k, v in request.items() if k != "request_key"})
        existing = conn.execute("SELECT * FROM request_keys WHERE project_id=? AND request_key=?", (project_id, request["request_key"])).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise ConflictError("This request key has already been used with different inputs.")
            return self.store.get(conn, "run", existing["run_id"], project_id)
        packages = [self.store.get(conn, "package", pid, project_id) for pid in request["package_ids"]]
        if request["policy_ids"]:
            packages = [self.draft(conn, project_id, pid) for pid in request["policy_ids"]]
        if any(p.get("generator") == "kimi-writer-v1" for p in packages):
            raise ValueError("Evaluate Kimi drafts through the submission studio to use the personalized semantic rubric.")
        if len({p["context_hash"] for p in packages}) != 1:
            raise ValueError("Saved packages have different public snapshots. Generate a new comparison from policies to align the context.")
        policies = [self.store.get(conn, "policy", package["policy_id"], project_id) for package in packages]
        if len(set(p["id"] for p in policies)) != len(policies):
            raise ValueError("Compare one saved package per policy version.")
        context = packages[0]["shared_context"]
        worlds = sample_worlds(request["seed"], request["worlds"], context, request["delay_days"], datetime.now(timezone.utc).date())
        identity = record_id("run")
        trial_ids = []
        for world in worlds:
            for package, policy in zip(packages, policies):
                evaluation = select(package, world)
                trial = self.store.add(conn, "trial", project_id, {
                    "run_id": identity, "policy_id": policy["id"], "package_id": package["id"],
                    "observation": {"passed": evaluation["passed"]}, "evaluation": evaluation,
                    "paired_block_id": world["hash"], "package_hash": package["content_hash"],
                    "context_hash": package["context_hash"], "origin": "reference-simulation",
                })
                trial_ids.append(trial["id"])
                self.store.event(conn, project_id, "feedback.recorded", {
                    "trial_id": trial["id"], "observation": trial["observation"]}, "feedback-gateway")
        result = self.store.add(conn, "run", project_id, {
            "project_id": project_id, "policy_ids": [p["id"] for p in policies],
            "package_ids": [p["id"] for p in packages], "trial_ids": trial_ids,
            "world_count": len(worlds), "seed": request["seed"], "delay_days": request["delay_days"],
            "context_snapshot": context, "context_hash": digest(context),
            "protocol": "binary-selection-v1", "origin": "reference-simulation",
            "suite_version": "illustrative-suite-v1", "evaluation_mode": "fixed-artifact-paired-worlds",
            "status": "completed", "intervention": "observer-requested" if actor == "observer" else "learner-requested",
            "cost": {"model_calls": 0, "model_tokens": 0, "external_cost_usd": 0,
                     "reference_evaluations": len(trial_ids), "elapsed_ms": round((time.perf_counter() - start) * 1000)},
        }, identity)
        conn.execute("INSERT INTO request_keys VALUES (?, ?, ?, ?)", (project_id, request["request_key"], request_hash, identity))
        self.store.event(conn, project_id, "run.completed", {"run_id": identity, "trial_count": len(trial_ids)}, actor)
        return result

    def run_detail(self, conn, project_id, run_id):
        run = self.store.get(conn, "run", run_id, project_id)
        trials = [self.store.get(conn, "trial", tid, project_id) for tid in run["trial_ids"]]
        summaries = []
        for policy_id in run["policy_ids"]:
            rows = [row for row in trials if row["policy_id"] == policy_id]
            summaries.append({"policy_id": policy_id, "passed": sum(row["observation"]["passed"] for row in rows),
                              "total": len(rows), "by_scenario": [
                {"scenario_id": s["id"], "name": s["name"],
                 "passed": sum(row["observation"]["passed"] for row in rows if row["evaluation"]["world"]["scenario"]["id"] == s["id"]),
                "total": sum(row["evaluation"]["world"]["scenario"]["id"] == s["id"] for row in rows)} for s in run.get("scenarios", SCENARIOS)]})
        return {**run, "summaries": summaries, "trials": trials}

    def workspace(self, conn, project_id):
        project = self.store.get(conn, "project", project_id)
        evidence = self.store.list(conn, "evidence", project_id)
        runs = self.store.list(conn, "run", project_id)
        return {"project": project, "evidence": evidence,
                "policies": self.store.list(conn, "policy", project_id),
                "packages": self.store.list(conn, "package", project_id),
                "runs": list(reversed(runs)), "scenarios": SCENARIOS,
                "context_hash": digest(public_context(project, evidence)),
                "events": self.store.list(conn, "event", project_id)[-150:]}
