"""Weighted overall + prioritisation (BACKEND.md §13).

Weights change only the overall number and display order — never re-score. The frontend
can recompute `overall` client-side with the same formula, so a slider needs no API call.
"""

from app.schema import CRITERIA, CoverageItem, CriterionScore, RiskFinding

_SEV = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_COV = {"CONTRADICTED": 3, "MISSING": 2, "PARTIAL": 1, "ADDRESSED": 0}


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    weights = weights or {}
    return {c: float(weights.get(c, 1.0)) for c in CRITERIA}


def weighted_overall(scores: list[CriterionScore], weights: dict[str, float]) -> float:
    num = den = 0.0
    for s in scores:
        w = float(weights.get(s.id, 1.0))
        num += w * s.score
        den += w
    return round(num / den, 2) if den else 0.0


def prioritize_coverage(
    coverage: list[CoverageItem], weights: dict[str, float]
) -> list[CoverageItem]:
    return sorted(coverage, key=lambda c: _COV.get(c.status, 0), reverse=True)


def prioritize_risks(risks: list[RiskFinding], weights: dict[str, float]) -> list[RiskFinding]:
    # risks carry no criterion; sort by severity only
    return sorted(risks, key=lambda k: _SEV.get(k.severity, 1), reverse=True)
