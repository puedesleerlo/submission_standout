from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    institution: str = Field(min_length=2, max_length=160)
    posting: str = Field(min_length=30, max_length=20000)
    deadline: date
    domain: Literal["Fellowship", "Grant", "Job"] = "Fellowship"
    focus: list[str] = Field(min_length=1, max_length=8)
    reservation_conditions: str = Field(default="", max_length=3000)

    @field_validator("focus")
    @classmethod
    def clean_focus(cls, value):
        cleaned = list(dict.fromkeys(term.strip().lower() for term in value if term.strip()))
        if not cleaned or any(len(term) > 70 for term in cleaned):
            raise ValueError("Use at least one focus term, each under 70 characters.")
        return cleaned


class EvidenceInput(StrictModel):
    title: str = Field(min_length=2, max_length=140)
    body: str = Field(min_length=15, max_length=20000)
    kind: Literal["Experience", "Research", "Artifact", "Idea", "Institution"] = "Experience"
    source: str = Field(default="", max_length=2000)
    status: Literal["User supplied", "Documented", "Hypothesis"] = "User supplied"


class PolicyConfig(StrictModel):
    framing: Literal["evidence", "delivery", "hypothesis", "mission"] = "evidence"
    evidence_limit: int = Field(default=3, ge=1, le=6)
    plan_depth: int = Field(default=1, ge=0, le=3)
    compare_alternative: bool = False


class PolicyInput(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    hypothesis: str = Field(min_length=10, max_length=2000)
    parents: list[str] = Field(default_factory=list, max_length=2)
    config: PolicyConfig

    @field_validator("parents")
    @classmethod
    def unique_parents(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Merge parents must be distinct.")
        return value


class DraftInput(StrictModel):
    policy_id: str


class RevisionInput(StrictModel):
    body: str = Field(min_length=30, max_length=20000)


class RunInput(StrictModel):
    policy_ids: list[str] = Field(default_factory=list, max_length=6)
    package_ids: list[str] = Field(default_factory=list, max_length=6)
    worlds: int = Field(default=12, ge=1, le=30)
    seed: int = Field(default=17, ge=0, le=2**31 - 1)
    request_key: str = Field(min_length=8, max_length=100)
    delay_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def choose_inputs(self):
        if bool(self.policy_ids) == bool(self.package_ids):
            raise ValueError("Choose policy versions or saved packages, but not both.")
        ids = self.policy_ids or self.package_ids
        if len(set(ids)) != len(ids):
            raise ValueError("Choose distinct inputs.")
        return self
