from datetime import datetime, timedelta, timezone


def seed_demo(service):
    store = service.store
    with store.connect(write=True) as conn:
        if store.list(conn, "project"):
            return
        project = service.create_project(conn, {
            "name": "Fieldnotes Research Fellowship", "institution": "Fieldnotes Institute",
            "domain": "Fellowship", "deadline": (datetime.now(timezone.utc).date() + timedelta(days=60)).isoformat(),
            "posting": "A fictional six-month fellowship exploring how public-interest technology can support climate adaptation. Fellows propose a tractable research question, build a small reproducible prototype, and communicate results to community partners. The illustrative program values credible evidence, careful methods, and useful work. This posting, institution, and applicant are synthetic examples.",
            "focus": ["climate adaptation", "public-interest technology", "reproducible"],
            "reservation_conditions": "Example constraints: no relocation; at most 20 hours per week; access to required data must be confirmed before committing.",
        }, synthetic=True)
        pid = project["id"]
        for item in [
            {"title": "Community heat mapping study", "kind": "Research", "body": "In this synthetic case study, I built a reproducible analysis of 1,240 temperature observations across 12 neighborhoods and documented the limits of the sampling method.", "source": "Synthetic research case note", "status": "Documented"},
            {"title": "Open data pipeline", "kind": "Artifact", "body": "In this synthetic project, I maintained an open data pipeline that combined 3 public datasets, added validation checks, and reduced a weekly preparation task from 4 hours to 35 minutes.", "source": "Synthetic portfolio record", "status": "Documented"},
            {"title": "Research with community partners", "kind": "Experience", "body": "In this synthetic example, I facilitated 6 research sessions with community partners, translated their questions into an evaluation protocol, and returned the findings in an accessible briefing.", "source": "Synthetic experience record", "status": "User supplied"},
            {"title": "Current institutional priorities", "kind": "Institution", "body": "The fictional institute prioritizes climate adaptation, public-interest technology, and reproducible research. Its actual selection weights are unknown; all three scenario families are illustrative assumptions.", "source": "Synthetic institutional brief", "status": "Hypothesis"},
        ]:
            store.add(conn, "evidence", pid, {**item, "synthetic": True})
        policies = []
        for name, hypothesis, config in [
            ("Evidence first", "Lead with inspectable prior work and make the claim-to-evidence connection explicit.", {"framing": "evidence", "evidence_limit": 3, "plan_depth": 1, "compare_alternative": False}),
            ("A credible delivery plan", "A clear schedule and bounded deliverables may perform better when execution dominates.", {"framing": "delivery", "evidence_limit": 2, "plan_depth": 3, "compare_alternative": False}),
            ("A distinctive research question", "A testable hypothesis and a serious alternative may perform better under novelty-led review.", {"framing": "hypothesis", "evidence_limit": 3, "plan_depth": 1, "compare_alternative": True}),
        ]:
            policies.append(service.create_policy(conn, pid, {"name": name, "hypothesis": hypothesis, "parents": [], "config": config}))
        service.run(conn, pid, {"policy_ids": [p["id"] for p in policies], "package_ids": [], "worlds": 12, "seed": 17, "delay_days": 0, "request_key": "initial-demo-comparison"})
