"""Weighted overall, code-computed completeness, ordering, finding de-duplication.
Weights never touch the LLM: this is the slider's whole cost."""

from app.aggregate import (
    completeness_from_coverage,
    dedupe_findings,
    normalize_weights,
    prioritize_coverage,
    prioritize_findings,
    prioritize_violations,
    weighted_overall,
)
from app.schema import (
    CRITERIA,
    ConstraintViolation,
    CoverageItem,
    CriterionScore,
    Finding,
    FindingType,
    Requirement,
    Severity,
)


def _scores(values: dict[str, int | None]) -> list[CriterionScore]:
    return [CriterionScore(id=c, score=values.get(c, 3), weaknesses="w") for c in CRITERIA]  # type: ignore[arg-type]


def _cov(rid: str, status: str, section: str | None = None) -> CoverageItem:
    return CoverageItem(
        requirementId=rid,
        status=status,  # type: ignore[arg-type]
        proposalSection=section,
        proposalQuote=None,
        explanation=None if status == "ADDRESSED" else "e",
        fix=None if status == "ADDRESSED" else "f",
    )


def _finding(type_: FindingType, sev: Severity, loc: str, quote: str) -> Finding:
    return Finding(
        type=type_, severity=sev, location=loc, proposalQuote=quote, explanation="e", fix="f"
    )


def test_normalize_weights_fills_all_seven_and_casts():
    w = normalize_weights({"pricing_clarity": 3, "bogus": 9})
    assert set(w) == set(CRITERIA) and w["pricing_clarity"] == 3.0 and w["completeness"] == 1.0
    assert "bogus" not in w
    assert normalize_weights(None) == dict.fromkeys(CRITERIA, 1.0)


def test_weighted_overall_skips_null_scores_and_returns_none_when_nothing_scored():
    scores = _scores({"pricing_clarity": 1})
    equal = normalize_weights(None)
    assert weighted_overall(scores, equal) == round(19 / 7, 2)
    heavier = normalize_weights({"pricing_clarity": 3})
    a, b = weighted_overall(scores, heavier), weighted_overall(scores, equal)
    assert a is not None and b is not None and a < b

    # completeness is null (no RFP): the mean is over the six that were scored
    six = _scores({"completeness": None, "pricing_clarity": 1})
    assert weighted_overall(six, equal) == round(16 / 6, 2)
    # a zero weight disables a criterion; all-zero or nothing scored → None
    assert weighted_overall(six, normalize_weights({"pricing_clarity": 0})) == 3.0
    assert weighted_overall(six, dict.fromkeys(CRITERIA, 0.0)) is None
    assert weighted_overall([], equal) is None
    assert weighted_overall(_scores(dict.fromkeys(CRITERIA)), equal) is None


def test_completeness_is_a_function_of_coverage():
    reqs = [Requirement(id=f"r{i}", label=f"Need {i}", rfpQuote="q") for i in range(1, 6)]
    cov = [
        _cov("r1", "ADDRESSED", "§2"),
        _cov("r2", "ADDRESSED", "§2"),
        _cov("r3", "PARTIAL", "§4"),
        _cov("r4", "MISSING"),
        # r5: the model gave no verdict → counts as 0
    ]
    s = completeness_from_coverage(cov, reqs)
    assert s.id == "completeness" and s.label == "Completeness vs. RFP Requirements"
    assert s.score == 3  # (1 + 1 + 0.5 + 0 + 0) / 5 = 0.5 → 1 + 4·0.5
    assert s.strengths and s.strengths.startswith(
        "2 of 5 requirements addressed: r1 Need 1, r2 Need 2"
    )
    assert "3 of 5 requirements not fully addressed" in s.weaknesses
    assert "r3 Need 3 (PARTIAL)" in s.weaknesses and "r5 Need 5 (NO VERDICT)" in s.weaknesses
    assert [(c.source, c.section, c.grounding) for c in s.citations] == [
        ("proposal", "§2", "verified"),
        ("proposal", "§4", "verified"),
    ]
    assert s.note and s.note.startswith("computed from coverage: 2.5/5")

    full = completeness_from_coverage([_cov(r.id, "ADDRESSED", "§1") for r in reqs], reqs)
    assert full.score == 5 and full.weaknesses == "Every requirement is addressed."
    none = completeness_from_coverage([_cov(r.id, "CONTRADICTED", "§1") for r in reqs], reqs)
    assert none.score == 1 and none.strengths is None
    no_rfp = completeness_from_coverage([], [])
    assert no_rfp.score is None and "no RFP" in (no_rfp.note or "")


def test_orderings():
    cov = [
        _cov("a", "ADDRESSED"),
        _cov("b", "PARTIAL"),
        _cov("c", "CONTRADICTED"),
        _cov("d", "MISSING"),
    ]
    assert [c.status for c in prioritize_coverage(cov)] == [
        "CONTRADICTED",
        "MISSING",
        "PARTIAL",
        "ADDRESSED",
    ]

    vio = [
        ConstraintViolation(
            constraintId="c1",
            proposalSection=None,
            proposalQuote="q",
            violation="v",
            severity="LOW",
            fix="f",
        ),
        ConstraintViolation(
            constraintId="c2",
            proposalSection=None,
            proposalQuote="q",
            violation="v",
            severity="HIGH",
            fix="f",
        ),
    ]
    assert [v.severity for v in prioritize_violations(vio)] == ["HIGH", "LOW"]

    fin = [
        _finding("VAGUENESS", "MEDIUM", "§1", "a"),
        _finding("OVERCOMMIT", "HIGH", "§1", "b"),
        _finding("SCOPE_CREEP", "LOW", "§1", "c"),
    ]
    assert [f.severity for f in prioritize_findings(fin)] == ["HIGH", "MEDIUM", "LOW"]


def test_dedupe_keeps_the_stronger_of_two_overlapping_quotes_in_the_same_section():
    a = _finding("UNREALISTIC_TIMELINE", "MEDIUM", "§3", "within **8 weeks**")
    b = _finding("SCOPE_CREEP", "HIGH", "§3", "8 weeks")  # substring of a, same section
    c = _finding("VAGUENESS", "LOW", "§4", "8 weeks")  # same words, other section → kept
    d = _finding("OVERCOMMIT", "LOW", "§3", "AI demand forecasting")
    out = dedupe_findings([a, b, c, d])
    assert [(f.type, f.severity) for f in out] == [
        ("SCOPE_CREEP", "HIGH"),
        ("VAGUENESS", "LOW"),
        ("OVERCOMMIT", "LOW"),
    ]
    assert dedupe_findings([]) == []
