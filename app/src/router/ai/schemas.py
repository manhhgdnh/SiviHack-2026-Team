from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]
Status = Literal["satisfied", "partial_or_unclear", "contradicted", "not_found"]
Severity = Literal["low", "medium", "high", "critical"]
CriterionName = Literal[
    "problem_understanding",
    "scope_deliverables_clarity",
    "pricing_clarity",
    "timeline_clarity",
    "completeness_vs_rfp",
    "tone_persuasiveness",
    "risk_assumptions_transparency",
]
CRITERIA = {
    "problem_understanding": "c-problem",
    "scope_deliverables_clarity": "c-scope",
    "pricing_clarity": "c-pricing",
    "timeline_clarity": "c-timeline",
    "completeness_vs_rfp": "c-completeness",
    "tone_persuasiveness": "c-tone",
    "risk_assumptions_transparency": "c-risk",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(StrictModel):
    source: Literal["rfp", "proposal"]
    section: str | None
    quote: Text


class RFPRequirement(StrictModel):
    id: Annotated[str, Field(pattern=r"^RFP-\d{3,}$")]
    category: Text
    requirement: Text
    mandatory: bool
    rfp_section: str | None
    rfp_quote: Text


class RFPExtraction(StrictModel):
    requirements: Annotated[list[RFPRequirement], Field(min_length=1, max_length=120)]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate requirement IDs")
        return self


class RequirementAssessment(StrictModel):
    requirement_id: Text
    status: Status
    severity: Severity
    explanation: Text
    rfp_evidence: Evidence
    proposal_evidence: list[Evidence]
    suggested_fix: str | None

    @model_validator(mode="after")
    def evidence_status(self):
        if self.rfp_evidence.source != "rfp":
            raise ValueError("RFP evidence must reference the RFP")
        if any(e.source != "proposal" for e in self.proposal_evidence):
            raise ValueError("Proposal evidence must reference the proposal")
        if (self.status == "not_found") != (len(self.proposal_evidence) == 0):
            raise ValueError("Only not_found has empty proposal evidence")
        if self.status != "satisfied" and not (self.suggested_fix or "").strip():
            raise ValueError("Every unsatisfied requirement needs an action")
        return self


class CriterionEvaluation(StrictModel):
    criterion: CriterionName
    score: Annotated[int, Field(ge=1, le=5, strict=True)]
    comment: Text
    strengths: list[Text]
    weaknesses: list[Text]
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    suggested_fix: str | None = None

    @model_validator(mode="after")
    def supported_strength(self):
        if self.score <= 2 and not (self.suggested_fix or "").strip():
            raise ValueError("A seriously weak criterion needs an actionable fix")
        if (self.score >= 4 or self.strengths) and not any(
            e.source == "proposal" for e in self.evidence
        ):
            raise ValueError("A strong score or strength requires proposal evidence")
        return self


class RiskFinding(StrictModel):
    criterion: CriterionName
    severity: Severity
    explanation: Text
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    suggested_fix: Text

    @model_validator(mode="after")
    def proposal_basis(self):
        if not any(e.source == "proposal" for e in self.evidence):
            raise ValueError("A risk finding needs proposal evidence")
        return self


class ProposalReview(StrictModel):
    requirement_assessments: list[RequirementAssessment]
    criteria: Annotated[list[CriterionEvaluation], Field(min_length=7, max_length=7)]
    risks: list[RiskFinding]

    @model_validator(mode="after")
    def complete_criteria(self):
        if {c.criterion for c in self.criteria} != set(CRITERIA):
            raise ValueError("Exactly one evaluation per official criterion is required")
        ids = [a.requirement_id for a in self.requirement_assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate assessments")
        return self


class CriterionSetting(StrictModel):
    id: Text
    name: str = ""
    whatToCheck: str = ""
    enabled: bool = True
    weight: Annotated[float, Field(ge=0, le=100)] = 1
    custom: bool = False


class ReviewInput(StrictModel):
    rfp: Annotated[str, Field(min_length=1, max_length=100_000)]
    proposal: Annotated[str, Field(min_length=1, max_length=100_000)]
    criteria: list[CriterionSetting] | None = None

    @model_validator(mode="after")
    def valid_input(self):
        if not self.rfp.strip() or not self.proposal.strip():
            raise ValueError("Both documents must contain text")
        if self.criteria is not None:
            ids = [c.id for c in self.criteria]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate criterion settings")
            if any(c.id not in CRITERIA.values() or c.custom for c in self.criteria):
                raise ValueError("This MVP supports the seven FPT criteria only")
            if sum(c.weight for c in self.criteria if c.enabled) <= 0:
                raise ValueError("At least one criterion needs positive enabled weight")
        return self


class Citation(StrictModel):
    witness: Literal["R", "P"]
    section: str
    from_: int = Field(alias="from", ge=1)
    to: int = Field(ge=1)


class UIRequirement(StrictModel):
    id: str
    ref: str
    section: str
    text: str
    status: Literal["addressed", "partial", "missing", "contradicted"]
    answeredAt: Citation | None
    source: Citation
    note: str
    severity: Severity
    mandatory: bool
    suggestedFix: str | None
    anchor_id: str
    rfp_evidence: Evidence
    proposal_evidence: list[Evidence]


class UIIssue(StrictModel):
    id: str
    ref: str
    severity: Literal["must", "should", "optional"]
    criterionId: str
    lemma: str
    quoted: str | None
    location: Citation
    against: Citation | None
    whyItMatters: str
    suggestedFix: str
    # These are review instructions, not source text or ready-to-send commitments.
    fixKind: Literal["action"] = "action"


class UICriterion(StrictModel):
    criterionId: str
    score: int
    strength: str | None
    weakness: str
    citations: list[Citation]
    comment: str


class Notification(StrictModel):
    type: Literal["contradiction"] = "contradiction"
    requirement_id: str
    severity: Severity
    message: str
    anchor_id: str


class ReviewResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    verdict: Literal["ready", "fix", "not-ready"]
    overall: float
    criteria: list[UICriterion]
    requirements: list[UIRequirement]
    issues: list[UIIssue]
    # Additive fields preserve the existing UI contract.
    counters: dict[str, int]
    notifications: list[Notification]
    overall_100: float
    readiness: Literal["ready", "minor_revision", "major_revision", "not_ready"]
    readiness_reasons: list[str]
    top_actions: list[str]
    review: ProposalReview
    metadata: dict[str, str | float | bool]
