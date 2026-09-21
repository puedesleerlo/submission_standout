"""Only tests import this deterministic provider. Production has no fake-model fallback."""
from backend.store import digest
from backend.llm import ModelError


class FakeModel:
    def __init__(self, store=None):
        self.store = store
        self.calls = []
        self.fail_role = None

    def describe(self):
        return {"configured": True, "model": "kimi-test-fixture", "provider": "Test fixture", "mode": "test", "max_calls_per_day": 100000}

    def complete(self, project_id, job_id, role, system, inputs, contract):
        self.calls.append({"role": role, "inputs": inputs, "job_id": job_id})
        if role == self.fail_role:
            raise ModelError("The test provider failed. No negative reward should be recorded.")
        dims = ["fit", "evidence", "feasibility", "originality", "voice"]
        if role == "selector_designer":
            result = {
                "institutional_interests": "The posting asks for reproducible, useful research with public-interest value.",
                "source_basis": ["Supplied posting"], "uncertainties": ["Applicant pool and actual judging weights are unknown."],
                "rubric": [{"dimension": d, "name": d.title(), "question": f"How well does the proposal demonstrate {d}?",
                            "strong": "Specific and grounded contribution with credible supporting evidence.", "weak": "Generic claims with no concrete supporting evidence."} for d in dims],
                "scenarios": [{"id": f"scenario-{i}", "name": f"SEALED_SELECTOR_SENTINEL {i}", "probability": p,
                               "rationale": "An explicitly uncertain scenario grounded in the supplied public posting.",
                               "rule": rule, "weights": dict.fromkeys(dims, .2), "minimum_score": 65, "places": 2}
                              for i, (p, rule) in enumerate(zip([.4, .35, .25], ["top_k", "threshold", "veto"]))],
                "rivals": [{"name": f"Counterfactual {i}", "description": "A synthetic applicant with coherent but uncertain strengths and limitations.",
                            "features": dict.fromkeys(dims, 60+i*5)} for i in range(3)],
            }
        elif role == 'research_planner':
            prior = inputs['available_policies']
            result = {'strategies': [{
                'name': f'Reusable policy {len(prior)+i}',
                'hypothesis': 'Specific evidence and bounded milestones help the reader assess the offer.',
                'instructions': 'Start with the institutional problem, select relevant factual support, and propose a bounded evaluation plan. Write plain and specific sentences.',
                'tradeoff': 'Emphasize verifiable results over breadth of aspiration.',
                'reflection': 'Previous observations are uncertain evidence, not proof of future performance.',
                'parents': [prior[-1]['id']] if prior else [], 'evidence_ids': [],
            } for i in range(2)]}
        elif role == "strategist":
            prior = inputs["available_policies"] if inputs["mode"] != "develop" else []
            result = {"strategies": [{"name": f"{'Refined' if prior else 'Initial'} approach {i+1}",
                "hypothesis": "Ground a distinctive proposal in concrete evidence and a limited deliverable.",
                "instructions": "Open with the institutional problem. Select the strongest evidence. State a bounded plan and use plain, specific writing.",
                "tradeoff": "Favor a testable contribution over claims of broad transformation.",
                "reflection": f"There are {len(inputs['selection_feedback'])} binary observations. Their causes remain unknown.",
                "parents": [prior[-1]["id"]] if prior and i == 0 else [],
                "evidence_ids": [e["id"] for e in inputs["applicant_evidence"][:3]],
            } for i in range(2)]}
        elif role == "writer":
            evidence = inputs["applicant_evidence"]
            result = {"title": inputs["strategy"]["name"],
                "body": "# A reproducible research contribution\n\nI propose a bounded study that connects the institution's questions to an inspectable result.\n\n" +
                    "\n\n".join(e["body"] for e in evidence) + "\n\n## Proposed work\n\nI would agree on a focused question, specify a baseline, and document the findings and their limitations for review. The first milestone is a short evaluation protocol. Proposed work depends on confirmed data access and a feasible schedule.",
                "claims": [{"claim": e["body"], "evidence_ids": [e["id"]]} for e in evidence],
                "missing_information": ["Confirm available data and exact submission limits."], "voice_notes": "Use direct sentences grounded in specific actions and observable outcomes."}
        elif role == "judge":
            result = {"ratings": [{"dimension": d, "score": 84, "explanation": f"PRIVATE_CRITIQUE_SENTINEL: the document provides concrete support for {d}."} for d in dims],
                "strengths": ["The evidence supports a concrete contribution."], "weaknesses": ["Clarify the actual evaluation dataset."],
                "style_flags": [], "unsupported_claims": [], "integrity_passed": True,
                "integrity_reason": "The historical claims are supported by attached evidence.", "format_passed": True,
                "format_reason": "The document matches the requested proposal format."}
        else:
            raise AssertionError(role)
        result = contract.model_validate(result).model_dump(mode="json")
        with self.store.connect(write=True) as conn:
            call = self.store.add(conn, "model_call", project_id, {"job_id": job_id, "role": role, "inputs": inputs,
                "system": system, "model": "kimi-test-fixture", "prompt_hash": digest([system, inputs])})
            self.store.add(conn, "model_result", project_id, {"call_id": call["id"], "job_id": job_id, "role": role,
                "status": "completed", "output": result, "usage": {"total_tokens": 100}, "elapsed_ms": 1})
        return result, call["id"]
