"""Application policy, not an FPT/ISO certification or probability model."""

from dataclasses import dataclass

from .schemas import CRITERIA, CriterionSetting, ProposalReview


@dataclass(frozen=True)
class ReadinessPolicy:
    high_issues_for_major: int = 2
    score_for_ready: float = 4.0
    score_for_major: float = 3.0
    score_for_not_ready: float = 2.0


DEFAULT_POLICY = ReadinessPolicy()
STATUSES = ("satisfied", "partial_or_unclear", "contradicted", "not_found")


def aggregate(
    review: ProposalReview,
    settings: list[CriterionSetting] | None,
    policy: ReadinessPolicy = DEFAULT_POLICY,
) -> dict:
    weights = (
        {v: 1.0 for v in CRITERIA.values()}
        if settings is None
        else {c.id: c.weight if c.enabled else 0.0 for c in settings}
    )
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Positive total weight required")
    mean = sum(weights.get(CRITERIA[c.criterion], 0) * c.score for c in review.criteria) / total
    assessments = review.requirement_assessments
    issues = [a for a in assessments if a.status != "satisfied"]
    counters = {s: sum(a.status == s for a in assessments) for s in STATUSES}
    critical_conflicts = [
        a for a in issues if a.status == "contradicted" and a.severity == "critical"
    ]
    critical_other = [a for a in issues if a.severity == "critical"]
    high = sum(a.severity in ("high", "critical") for a in issues) + sum(
        r.severity in ("high", "critical") for r in review.risks
    )
    reasons = []
    if critical_conflicts:
        readiness = "not_ready"
        reasons = [
            f"{a.requirement_id}: explicit binding constraint contradicted."
            for a in critical_conflicts
        ]
    elif any(r.severity == "critical" for r in review.risks):
        readiness = "not_ready"
        reasons = ["A critical delivery risk requires human review."]
    elif critical_other or counters["contradicted"] or high >= policy.high_issues_for_major:
        readiness = "major_revision"
        reasons = [
            "Material requirement gaps or conflicts require revision, regardless of score weights."
        ]
    elif mean < policy.score_for_not_ready:
        readiness = "not_ready"
        reasons = ["Criterion scores show substantial deficiencies."]
    elif mean < policy.score_for_major or any(c.score <= 2 for c in review.criteria):
        readiness = "major_revision"
        reasons = [
            "At least one official criterion has important weaknesses, or the aggregate is low."
        ]
    elif (
        issues
        or review.risks
        or mean < policy.score_for_ready
        or any(c.weaknesses for c in review.criteria)
    ):
        readiness = "minor_revision"
        reasons = ["Address the remaining qualifications and weaknesses before sending."]
    else:
        readiness = "ready"
        reasons = [
            "No material issue identified in the reviewed text; a human must confirm the commitments."
        ]
    return {
        "overall": round(mean + 1e-10, 1),
        "overall_100": round(mean * 20, 1),
        "counters": counters,
        "readiness": readiness,
        "readiness_reasons": reasons,
        "verdict": {
            "ready": "ready",
            "minor_revision": "fix",
            "major_revision": "fix",
            "not_ready": "not-ready",
        }[readiness],
    }
