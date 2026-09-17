"""Weighted overall, code-computed completeness, prioritisation, finding de-duplication.

Weights change only the overall number and display order — never re-score, never reach the
LLM, never enter a cache key. Dragging a slider is a pure recomputation here (or client-side
with the same formula), not an LLM call.
"""

from app.normalize import normalize
from app.schema import (
    CRITERIA,
    CRITERION_LABELS,
    Citation,
    ConstraintViolation,
    CoverageItem,
    CriterionScore,
    Finding,
    Requirement,
)

_SEV = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_COV = {"CONTRADICTED": 3, "MISSING": 2, "PARTIAL": 1, "ADDRESSED": 0}
COMPLETENESS_CREDIT = {"ADDRESSED": 1.0, "PARTIAL": 0.5, "MISSING": 0.0, "CONTRADICTED": 0.0}


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    weights = weights or {}
    return {c: float(weights.get(c, 1.0)) for c in CRITERIA}


def weighted_overall(scores: list[CriterionScore], weights: dict[str, float]) -> float | None:
    """Σ(score × weight) / Σ(weight) over criteria that have a score. None if none do."""
    num = den = 0.0
    for s in scores:
        if s.score is None:
            continue  # not assessable (e.g. completeness without an RFP) — not a 0
        w = float(weights.get(s.id, 1.0))
        num += w * s.score
        den += w
    return round(num / den, 2) if den else None


def completeness_from_coverage(
    coverage: list[CoverageItem], requirements: list[Requirement]
) -> CriterionScore:
    """Criterion 5 is a function of coverage, so code computes it: ADDRESSED = 1, PARTIAL = ½,
    MISSING / CONTRADICTED / no verdict = 0, mapped onto 1–5. Deterministic and explainable."""
    if not requirements:
        return CriterionScore(
            id="completeness",
            label=CRITERION_LABELS["completeness"],
            score=None,
            weaknesses="",
            note="not assessable: no RFP provided",
        )
    by_req = {c.requirementId: c for c in coverage}
    credit = 0.0
    addressed: list[str] = []
    gaps: list[str] = []
    sections: list[str] = []
    for r in requirements:
        c = by_req.get(r.id)
        status = c.status if c else "NO VERDICT"
        credit += COMPLETENESS_CREDIT.get(status, 0.0)
        if status == "ADDRESSED":
            addressed.append(f"{r.id} {r.label}")
        else:
            gaps.append(f"{r.id} {r.label} ({status})")
        if c and c.proposalSection and c.status in ("ADDRESSED", "PARTIAL"):
            if c.proposalSection not in sections:
                sections.append(c.proposalSection)
    n = len(requirements)
    return CriterionScore(
        id="completeness",
        label=CRITERION_LABELS["completeness"],
        score=max(1, min(5, round(1 + 4 * credit / n))),
        strengths=f"{len(addressed)} of {n} requirements addressed: {', '.join(addressed)}."
        if addressed
        else None,
        weaknesses=f"{len(gaps)} of {n} requirements not fully addressed: {'; '.join(gaps)}."
        if gaps
        else "Every requirement is addressed.",
        citations=[Citation(source="proposal", section=s, grounding="verified") for s in sections],
        note=f"computed from coverage: {credit:g}/{n} credit "
        "(ADDRESSED = 1, PARTIAL = 0.5, MISSING / CONTRADICTED = 0)",
    )


def prioritize_coverage(coverage: list[CoverageItem]) -> list[CoverageItem]:
    return sorted(coverage, key=lambda c: _COV.get(c.status, 0), reverse=True)


def prioritize_violations(violations: list[ConstraintViolation]) -> list[ConstraintViolation]:
    return sorted(violations, key=lambda v: _SEV.get(v.severity, 1), reverse=True)


def prioritize_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: _SEV.get(f.severity, 1), reverse=True)


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Parallel scoring groups can flag the same sentence. Two findings are duplicates when
    they sit in the same section and one normalised quote contains the other (groups rarely
    cut the sentence at the same word). The higher severity survives; ties keep the first."""
    kept: list[Finding] = []
    for f in sorted(findings, key=lambda f: _SEV.get(f.severity, 1), reverse=True):
        q = normalize(f.proposalQuote)
        dup = any(
            k.location == f.location
            and (q in normalize(k.proposalQuote) or normalize(k.proposalQuote) in q)
            for k in kept
        )
        if not dup:
            kept.append(f)
    return kept
