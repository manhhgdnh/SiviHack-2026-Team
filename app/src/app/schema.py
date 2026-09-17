"""Pydantic v2 models — the source of truth for the API and the LLM outputs (BACKEND.md §8).

Field names are camelCase on purpose: they are the wire contract with the frontend.
"""

from typing import Literal

from pydantic import BaseModel, Field

# 7 fixed criteria (ids MUST match what the prompt emits)
CRITERIA: list[str] = [
    "problem_understanding",
    "scope_clarity",
    "pricing_clarity",
    "timeline_clarity",
    "completeness",
    "tone_persuasiveness",
    "risk_transparency",
]
type CriterionId = Literal[
    "problem_understanding",
    "scope_clarity",
    "pricing_clarity",
    "timeline_clarity",
    "completeness",
    "tone_persuasiveness",
    "risk_transparency",
]
type CoverageStatus = Literal["ADDRESSED", "PARTIAL", "MISSING", "CONTRADICTED"]
type Severity = Literal["HIGH", "MEDIUM", "LOW"]
type RiskType = Literal[
    "OVERCOMMIT", "SCOPE_CREEP", "UNREALISTIC_TIMELINE", "PRICING_MISMATCH", "CONTRADICTION"
]


class Requirement(BaseModel):
    id: str
    label: str
    rfpQuote: str  # verbatim from RFP
    section: str | None = None
    grounded: bool = False  # set by the validator, not the LLM


class CoverageItem(BaseModel):
    requirementId: str
    status: CoverageStatus
    proposalQuote: str | None = None  # verbatim, null if MISSING
    explanation: str
    fix: str
    grounded: bool = False


class CriterionScore(BaseModel):
    id: CriterionId
    label: str
    score: int = Field(ge=1, le=5)
    rationale: str
    evidenceQuote: str | None = None
    source: Literal["proposal", "rfp"] | None = None
    grounded: bool = False


class RiskFinding(BaseModel):
    type: RiskType
    proposalQuote: str
    rfpQuote: str | None = None
    explanation: str
    severity: Severity
    grounded: bool = False


# ---- LLM call 1 output ----
class RfpExtraction(BaseModel):
    requirements: list[Requirement]


# ---- LLM call 2 output (pre-grounding/aggregation) ----
class ScoreLlmOutput(BaseModel):
    coverage: list[CoverageItem]
    scores: list[CriterionScore]
    risks: list[RiskFinding]


# ---- API request / response ----
class ScoreRequest(BaseModel):
    rfp: str
    proposal: str
    weights: dict[str, float] | None = None  # e.g. {"pricing_clarity": 2}


class ScoringMeta(BaseModel):
    model: str
    temperature: float
    durationMs: int
    ungroundedDropped: int
    cacheHit: bool = False


class ScoringResult(BaseModel):
    overall: float
    weights: dict[str, float]
    scores: list[CriterionScore]
    coverage: list[CoverageItem]
    risks: list[RiskFinding]
    requirements: list[Requirement]
    meta: ScoringMeta
