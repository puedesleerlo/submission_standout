from typing import Literal

from pydantic import Field, model_validator

from backend.schemas import StrictModel

DIMENSIONS = {"fit", "evidence", "feasibility", "originality", "voice"}


class Criterion(StrictModel):
    dimension: Literal["fit", "evidence", "feasibility", "originality", "voice"]
    name: str = Field(min_length=2, max_length=100)
    question: str = Field(min_length=10, max_length=1200)
    strong: str = Field(min_length=10, max_length=1000)
    weak: str = Field(min_length=10, max_length=1000)


class Scenario(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    name: str = Field(min_length=2, max_length=100)
    probability: float = Field(gt=0, le=1)
    rationale: str = Field(min_length=10, max_length=1500)
    rule: Literal["top_k", "threshold", "veto", "rolling"]
    weights: dict[str, float]
    minimum_score: float = Field(ge=40, le=95)
    places: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def validate_weights(self):
        if set(self.weights) != DIMENSIONS or any(v < 0 or v > 1 for v in self.weights.values()) or abs(sum(self.weights.values())-1) > .011:
            raise ValueError("Every scenario needs exactly five normalized, nonnegative weights.")
        if self.weights["voice"] < .15:
            raise ValueError("Voice must retain at least 15% weight in every scenario.")
        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}
        return self


class Rival(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=20, max_length=1500)
    features: dict[str, float]

    @model_validator(mode="after")
    def valid_features(self):
        if set(self.features) != DIMENSIONS or any(v < 0 or v > 100 for v in self.features.values()):
            raise ValueError("Rival features must cover each rubric dimension on a 0–100 scale.")
        return self


class SelectionDesign(StrictModel):
    institutional_interests: str = Field(min_length=20, max_length=3000)
    source_basis: list[str] = Field(min_length=1, max_length=10)
    uncertainties: list[str] = Field(min_length=1, max_length=12)
    rubric: list[Criterion] = Field(min_length=5, max_length=5)
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)
    rivals: list[Rival] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def valid_design(self):
        if {r.dimension for r in self.rubric} != DIMENSIONS:
            raise ValueError("Rubric dimensions must be unique.")
        if len({s.id for s in self.scenarios}) != 3 or abs(sum(s.probability for s in self.scenarios)-1) > .011:
            raise ValueError("Scenario IDs must be distinct and probabilities normalized.")
        total = sum(s.probability for s in self.scenarios)
        for scenario in self.scenarios:
            scenario.probability /= total
        return self


class Strategy(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    hypothesis: str = Field(min_length=10, max_length=1500)
    instructions: str = Field(min_length=40, max_length=4500)
    tradeoff: str = Field(min_length=10, max_length=1500)
    reflection: str = Field(min_length=10, max_length=2000)
    parents: list[str] = Field(max_length=2)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class StrategyBatch(StrictModel):
    strategies: list[Strategy] = Field(min_length=2, max_length=2)


class Claim(StrictModel):
    claim: str = Field(min_length=5, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class WrittenPackage(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=100, max_length=24000)
    claims: list[Claim] = Field(min_length=1, max_length=30)
    missing_information: list[str] = Field(max_length=12)
    voice_notes: str = Field(min_length=10, max_length=1500)


class Rating(StrictModel):
    dimension: Literal["fit", "evidence", "feasibility", "originality", "voice"]
    score: float = Field(ge=0, le=100)
    explanation: str = Field(min_length=15, max_length=2000)


class Judgment(StrictModel):
    ratings: list[Rating] = Field(min_length=5, max_length=5)
    strengths: list[str] = Field(min_length=1, max_length=6)
    weaknesses: list[str] = Field(min_length=1, max_length=6)
    style_flags: list[str] = Field(max_length=12)
    unsupported_claims: list[str] = Field(max_length=12)
    integrity_passed: bool
    integrity_reason: str = Field(min_length=10, max_length=2000)
    format_passed: bool
    format_reason: str = Field(min_length=10, max_length=1500)

    @model_validator(mode="after")
    def dimensions_complete(self):
        if {r.dimension for r in self.ratings} != DIMENSIONS:
            raise ValueError("Judge must rate all five distinct dimensions.")
        if self.unsupported_claims and self.integrity_passed:
            raise ValueError("Unsupported factual claims cannot pass the integrity gate.")
        return self


class AgentRequest(StrictModel):
    mode: Literal["develop", "iterate", "evaluate"] = "develop"
    artifact_type: Literal["Proposal", "Cover letter", "Resume", "Supporting statement"] = "Proposal"
    brief: str = Field(default="", max_length=3000)
    request_key: str = Field(min_length=8, max_length=100)
    package_id: str | None = None

    @model_validator(mode="after")
    def saved_input(self):
        if (self.mode == "evaluate") != bool(self.package_id):
            raise ValueError("Evaluate requires one saved package; other modes do not accept a package.")
        return self
