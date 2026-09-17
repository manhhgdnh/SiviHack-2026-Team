"""Pydantic v2 models — the source of truth for the API and the LLM outputs.

Field names are camelCase on purpose: they are the wire contract with the frontend.

Three things about the LLM-output models matter more than they look:

* **Field order is reasoning order.** The model generates JSON sequentially. Every output
  model puts analysis before conclusions: coverage → constraint violations → findings →
  scores. Do not reorder.
* **Output is kept small.** Quotes appear only where a reader needs the exact words
  (findings, violations, PARTIAL / CONTRADICTED coverage) and are capped at 20 words in the
  prompt. Citations on scores are section ids, not sentences: the UI already has the text.
* **`grounding` is code-owned.** It is never in the schema sent to the LLM (see
  `llm.llm_schema`); the grounding pass sets it after the fact.
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
CRITERION_LABELS: dict[str, str] = {
    "problem_understanding": "Problem Understanding",
    "scope_clarity": "Scope & Deliverables Clarity",
    "pricing_clarity": "Pricing Clarity",
    "timeline_clarity": "Timeline Clarity",
    "completeness": "Completeness vs. RFP Requirements",
    "tone_persuasiveness": "Tone & Persuasiveness",
    "risk_transparency": "Risk/Assumptions Transparency",
}
# completeness is a function of coverage (ADDRESSED=1, PARTIAL=0.5, else 0) and is computed
# by code — the model never scores it.
LLM_CRITERIA: list[str] = [c for c in CRITERIA if c != "completeness"]

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
type ConstraintKind = Literal["BUDGET", "DEADLINE", "TECHNOLOGY", "SCOPE", "LEGAL", "OTHER"]
# CONTRADICTION is deliberately absent: violating a client constraint is a
# ConstraintViolation, a different and heavier class of error than a risk finding.
type FindingType = Literal[
    "OVERCOMMIT",
    "SCOPE_CREEP",
    "UNREALISTIC_TIMELINE",
    "PRICING_MISMATCH",
    "VAGUENESS",
    "INCONSISTENCY",
]
type Source = Literal["proposal", "rfp"]
# verified = verbatim in the section it claims (or the section id exists, for citations);
# fuzzy = found, but paraphrased or in a different section (location corrected by code);
# unverified = not found → dropped.
type GroundingStatus = Literal["verified", "fuzzy", "unverified"]
type ScoringMode = Literal["split", "merged"]


# ---- shared ----
class SectionRef(BaseModel):
    id: str  # "§2", "§3.1", "¶4", "§0" (title / preamble)
    header: str


class Citation(BaseModel):
    """A pointer to a section of one of the two documents. No sentence: the UI has the text."""

    source: Source
    section: str  # section id; must exist in that document
    grounding: GroundingStatus | None = None


# ---- LLM call 1 output: what the RFP asks for, and what it forbids ----
class Requirement(BaseModel):
    id: str  # r1, r2, ...
    label: str
    rfpQuote: str  # verbatim from the RFP, ≤ 20 words
    section: str | None = None
    grounding: GroundingStatus | None = None


class Constraint(BaseModel):
    """A hard limit the proposal must not cross: budget ceiling, deadline, excluded
    technology, must-keep system. Distinct from requirements (things to deliver)."""

    id: str  # c1, c2, ...
    kind: ConstraintKind
    label: str
    rfpQuote: str  # verbatim from the RFP, ≤ 20 words
    section: str | None = None
    grounding: GroundingStatus | None = None


class WeightSuggestion(BaseModel):
    criterionId: CriterionId
    weight: float = Field(ge=0, le=5)  # relative, 1 = neutral
    reason: str


class RfpExtraction(BaseModel):
    requirements: list[Requirement]
    constraints: list[Constraint]
    suggestedWeights: list[WeightSuggestion] = []


# ---- LLM call 2 building blocks ----
class CoverageItem(BaseModel):
    requirementId: str
    status: CoverageStatus
    # required-but-nullable on purpose: the model must write explicit nulls rather than be
    # allowed to omit fields. ADDRESSED carries only the section; MISSING only the fix.
    proposalSection: str | None  # where it is addressed; null if MISSING
    proposalQuote: str | None  # ≤ 20 words, only for PARTIAL / CONTRADICTED
    explanation: str | None  # ≤ 15 words, null if ADDRESSED
    fix: str | None  # one sentence, null if ADDRESSED
    grounding: GroundingStatus | None = None


class ConstraintViolation(BaseModel):
    constraintId: str
    proposalSection: str | None
    proposalQuote: str  # verbatim, ≤ 20 words: the sentence that crosses the line
    violation: str  # what limit is crossed, and by how much
    severity: Severity
    fix: str
    grounding: GroundingStatus | None = None


class Finding(BaseModel):
    type: FindingType
    severity: Severity
    location: str | None = None  # proposal section id
    proposalQuote: str  # verbatim, ≤ 20 words
    explanation: str
    fix: str  # one concrete action that removes the issue
    grounding: GroundingStatus | None = None


class CriterionScore(BaseModel):
    id: CriterionId
    label: str = ""  # filled by code from CRITERION_LABELS
    score: int | None = Field(ge=1, le=5)  # required-but-nullable; null = not assessable
    strengths: str | None = None  # one sentence, or null
    weaknesses: str  # one sentence naming the exact gap
    citations: list[Citation] = []
    note: str | None = None  # e.g. "not assessable: no RFP provided"


# ---- LLM call 2 output shapes — ORDER IS REASONING ORDER ----
class CoverageLlmOutput(BaseModel):
    """Call 2a (split mode): triage. Small, mostly ids and enums."""

    coverage: list[CoverageItem]
    constraintViolations: list[ConstraintViolation]


class GroupLlmOutput(BaseModel):
    """Call 2b-i (split mode): one group of criteria. Findings first, then the scores they
    justify."""

    findings: list[Finding]
    scores: list[CriterionScore]


class ScoreLlmOutput(BaseModel):
    """Merged mode (local model): everything in one call, same order of reasoning."""

    coverage: list[CoverageItem]
    constraintViolations: list[ConstraintViolation]
    findings: list[Finding]
    scores: list[CriterionScore]


# ---- deterministic signals (code, before call 2) ----
class VagueHit(BaseModel):
    phrase: str
    section: str | None
    context: str


class Mention(BaseModel):
    value: str
    section: str | None


class NumericSignal(BaseModel):
    sections: list[str] = []  # ids of sections whose header says pricing / timeline
    mentions: list[Mention] = []  # money amounts / dates & durations, whole document


class Signals(BaseModel):
    vaguePhrases: list[VagueHit] = []
    pricing: NumericSignal = NumericSignal()
    timeline: NumericSignal = NumericSignal()


# ---- API request / response ----
class ScoreRequest(BaseModel):
    rfp: str = ""  # optional: without it, coverage is empty and completeness is null
    proposal: str
    weights: dict[str, float] | None = None  # e.g. {"pricing_clarity": 2}; never sent to the LLM


class DocOutline(BaseModel):
    count: int
    sections: list[SectionRef]


class ScoringMeta(BaseModel):
    model: str
    temperature: float
    promptVersion: str
    mode: ScoringMode = "merged"
    durationMs: int
    llmCalls: int = 0  # calls actually made (cache hits excluded)
    truncated: int = 0  # outputs cut at max tokens (salvaged with json_repair when possible)
    repaired: int = 0  # outputs that needed json_repair to parse
    ungroundedDropped: int = 0
    fuzzyMatched: int = 0
    extractCached: bool = False
    scoreCached: bool = False  # every scoring call was a cache hit


class ScoringResult(BaseModel):
    overall: float | None  # None when partial or nothing scorable
    weights: dict[str, float]
    scores: list[CriterionScore]
    coverage: list[CoverageItem]
    constraintViolations: list[ConstraintViolation]
    findings: list[Finding]
    requirements: list[Requirement]
    constraints: list[Constraint]
    suggestedWeights: list[WeightSuggestion]
    signals: Signals
    sections: dict[Source, DocOutline]
    partial: bool = False  # something is missing: see `error` / `warnings`
    error: str | None = None  # a call failed outright
    warnings: list[str] = []  # e.g. a truncated output was salvaged, a group failed
    meta: ScoringMeta


# ---- SSE event payloads (POST /score/stream), in emission order ----
class SectionsEvent(BaseModel):
    rfp: DocOutline
    proposal: DocOutline


class RequirementsEvent(BaseModel):  # right after LLM call 1
    requirements: list[Requirement]
    constraints: list[Constraint]
    suggestedWeights: list[WeightSuggestion]
    extractCached: bool


class CoverageEvent(BaseModel):  # right after call 2a (split) / the merged call
    coverage: list[CoverageItem]
    constraintViolations: list[ConstraintViolation]


class ScoresEvent(BaseModel):  # after every scoring call has returned and been grounded
    scores: list[CriterionScore]
    overall: float | None


class FindingsEvent(BaseModel):
    findings: list[Finding]


class ErrorEvent(BaseModel):
    stage: str
    error: str


# `done` carries the full ScoringResult.
type EventPayload = (
    SectionsEvent
    | RequirementsEvent
    | CoverageEvent
    | ScoresEvent
    | FindingsEvent
    | ErrorEvent
    | ScoringResult
)
