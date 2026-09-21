"""Transparent reference simulator. No LLM calls or real acceptance estimates.

The compositor executes typed policy settings. The judge uses deliberately simple
text features to exercise the experiment protocol, not to validate writing quality.
"""
from datetime import date, timedelta
import random
import re

from backend.store import digest

DIMENSIONS = ["fit", "evidence", "feasibility", "originality", "voice"]
SCENARIOS = [
    {"id": "delivery", "name": "Reliable delivery", "probability": 0.45,
     "weights": {"fit": .20, "evidence": .25, "feasibility": .35, "originality": .10, "voice": .10}},
    {"id": "discovery", "name": "Frontier discovery", "probability": 0.30,
     "weights": {"fit": .20, "evidence": .15, "feasibility": .15, "originality": .40, "voice": .10}},
    {"id": "mission", "name": "Mission contribution", "probability": 0.25,
     "weights": {"fit": .40, "evidence": .25, "feasibility": .10, "originality": .10, "voice": .15}},
]
RIVAL_PROFILES = [
    ("Established specialist", [85, 88, 64, 54, 76]),
    ("Proven operator", [69, 82, 91, 43, 81]),
    ("Original challenger", [73, 54, 54, 94, 74]),
    ("Mission-aligned generalist", [92, 65, 70, 60, 80]),
]
STYLE_PHRASES = ["delve", "uniquely positioned", "passionate about", "ever-evolving landscape", "leverage my", "game-changing"]


def public_context(project, evidence):
    return {**{key: project[key] for key in ["name", "institution", "posting", "deadline", "focus", "domain", "synthetic"]},
            "sources": [item for item in evidence if item["kind"] == "Institution"]}


def compose(project, policy, evidence):
    selected = [item for item in evidence if item["kind"] not in ["Institution", "Idea"] and item["status"] != "Hypothesis"][:policy["config"]["evidence_limit"]]
    if not selected:
        raise ValueError("Add at least one experience, research, or artifact item before generating a draft.")
    cfg = policy["config"]
    topics = ", ".join(project["focus"])
    openings = {
        "evidence": f"I propose contributing to {project['institution']} through work on {topics}. The experience below is the basis for that proposal.",
        "delivery": f"For {project['name']}, I would start with a bounded project on {topics}. The plan below separates the first useful deliverable from the broader research questions.",
        "hypothesis": f"My proposed hypothesis is that a focused intervention in {project['focus'][0]} can improve how we approach {topics}. I would test this against a clearly specified baseline before expanding the scope.",
        "mission": f"My proposed contribution to {project['institution']} centers on {topics}, the focus of this opportunity. I would first confirm the team's immediate needs and the evidence required to demonstrate a useful result.",
    }
    paragraphs = [openings[cfg["framing"]], "Relevant evidence"]
    for i, item in enumerate(selected, 1):
        paragraphs.append(f"[{i}] {item['body']}")
    paragraphs += ["Proposed contribution", f"I would use this experience to define a tractable question with the team, document the assumptions, and make the resulting work inspectable. The scope would remain open to discussion until the available resources and responsibilities are clear. The examples above describe prior work; the activities below are proposed work, not completed accomplishments."]
    if cfg["compare_alternative"]:
        paragraphs.append("I would compare the proposed approach with an alternative, test the hypothesis against a baseline, and report a negative result if the evidence does not support it. The question is which approach delivers a meaningful improvement under the same constraints.")
    milestones = [
        "Week 1: agree on the question, inspect the available evidence, and define the baseline. The first deliverable is a short protocol with an explicit evaluation method.",
        "Week 3: build a small prototype and evaluate it against the baseline. Review dependencies and revise the scope if data or access is unavailable.",
        "Week 6: document the results, limitations, and reproducible artifacts. The final deliverable includes what worked, what failed, and what should be tested next.",
    ]
    if cfg["plan_depth"]:
        paragraphs += ["Work plan", *milestones[:cfg["plan_depth"]]]
    paragraphs.append("Before committing, I would confirm the schedule, access requirements, and responsibilities. I would keep claims tied to the supplied evidence and distinguish proposed work from demonstrated results.")
    context = public_context(project, evidence)
    return {
        "policy_id": policy["id"], "body": "\n\n".join(paragraphs),
        "evidence_snapshot": selected, "shared_context": context,
        "context_hash": digest(context), "evidence_hash": digest(selected),
        "constraints_snapshot": project["reservation_conditions"],
        "generator": "reference-compositor-v1", "parent_id": None,
        "synthetic": project["synthetic"], "human_edited": False,
    }


def assess(package):
    body = package["body"]
    lower = body.lower()
    words = len(body.split())
    focus = package["shared_context"]["focus"]
    matched = [term for term in focus if term.lower() in lower]
    # Count only submitted evidence whose exact text remains in the document.
    supported = [item for item in package["evidence_snapshot"] if item["body"] in body]
    quantified = sum(bool(re.search(r"\d", item["body"])) for item in supported)
    milestones = list(dict.fromkeys(re.findall(r"\b(?:week|month)\s+\d+", lower)))
    plan_terms = [term for term in ["deliverable", "baseline", "dependencies", "evaluate"] if term in lower]
    original_terms = [term for term in ["hypothesis", "alternative", "compare", "negative result"] if term in lower]
    phrases = [term for term in STYLE_PHRASES if term in lower]
    values = {
        "fit": round(100 * len(matched) / max(1, len(focus))),
        "evidence": min(100, 25 + 16 * len(supported) + 5 * quantified),
        "feasibility": min(100, 20 + 16 * len(milestones) + 7 * len(plan_terms)),
        "originality": min(100, 25 + 17 * len(original_terms)),
        "voice": max(0, round(100 - 14 * len(phrases) - max(0, words - 550) * .12)),
    }
    reasons = {
        "fit": f"Matched focus terms: {', '.join(matched) or 'none'}. This measures keyword coverage, not semantic fit.",
        "evidence": f"{len(supported)} supplied evidence passages remain verbatim; {quantified} include numbers. This does not independently verify their truth.",
        "feasibility": f"{len(milestones)} distinct dated milestones and {len(plan_terms)} planning terms. This measures plan structure, not delivery feasibility.",
        "originality": f"{len(original_terms)} comparison or hypothesis terms. This is a test feature, not a claim of actual novelty.",
        "voice": f"{len(phrases)} flagged stock phrases in {words} words. User review is still required.",
    }
    return {"ratings": [{"dimension": dim, "score": values[dim], "explanation": reasons[dim]} for dim in DIMENSIONS],
            "values": values, "word_count": words, "style_flags": phrases,
            "supported_count": len(supported), "evaluator": "reference-heuristics-v1"}


def sample_worlds(seed, count, context, delay_days=0, today=None):
    rng = random.Random(seed)
    arrival = (today or date.today()) + timedelta(days=delay_days)
    worlds = []
    for index in range(count):
        scenario = rng.choices(SCENARIOS, weights=[s["probability"] for s in SCENARIOS])[0]
        rivals = []
        for name, means in RIVAL_PROFILES:
            values = {dim: max(0, min(100, round(rng.gauss(mean, 7)))) for dim, mean in zip(DIMENSIONS, means)}
            rivals.append({"name": name, "features": values, "score": weighted(values, scenario["weights"]), "origin": "synthetic-feature-profile"})
        world = {"index": index, "scenario": scenario, "rivals": rivals, "places": 2,
                 "minimum_score": 60, "arrival_date": arrival.isoformat(), "deadline": context["deadline"],
                 "rule": "top_k", "tie_break": "reference rivals precede candidate on exact ties",
                 "suite_version": "illustrative-suite-v1"}
        world["hash"] = digest(world)
        worlds.append(world)
    return worlds


def weighted(values, weights):
    return round(sum(values[dim] * weights[dim] for dim in DIMENSIONS), 2)


def select(package, world):
    assessment = assess(package)
    gates = [
        {"name": "Within deadline (UTC date)", "passed": world["arrival_date"] <= world["deadline"]},
        {"name": "Reference format: 100–800 words", "passed": 100 <= assessment["word_count"] <= 800},
        {"name": "At least one attached evidence passage", "passed": assessment["supported_count"] > 0},
    ]
    score = weighted(assessment["values"], world["scenario"]["weights"])
    rank = 1 + sum(rival["score"] >= score for rival in world["rivals"])
    passed = all(gate["passed"] for gate in gates) and score >= world["minimum_score"] and rank <= world["places"]
    if not all(gate["passed"] for gate in gates):
        reason = "A required reference gate failed."
    elif score < world["minimum_score"]:
        reason = "The package did not clear the reference minimum score."
    elif rank > world["places"]:
        reason = "The package ranked below the available places in this synthetic pool."
    else:
        reason = "The package cleared the gates and ranked within the available places."
    return {**assessment, "score": score, "rank": rank, "passed": passed, "gates": gates,
            "reason": reason, "world": world, "rubric_version": "reference-rubric-v1"}
