"""Quote verification: normalised, fuzzy, pinned to the claimed section; section-pointer
citations; code-computed completeness; cross-group de-duplication."""

from pathlib import Path

import pytest

from app import config
from app.grounding import (
    GroundingStats,
    _ground_citations,
    ground_extraction,
    ground_scoring,
    verify,
)
from app.normalize import normalize
from app.schema import (
    CRITERIA,
    Citation,
    Constraint,
    ConstraintViolation,
    CoverageItem,
    CoverageStatus,
    CriterionScore,
    Finding,
    Requirement,
    RfpExtraction,
    ScoreLlmOutput,
)
from app.splitter import parse

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
RFP = parse((SAMPLES / "rfp_nordframe.md").read_text())
WEAK = parse((SAMPLES / "response_1_weak.md").read_text())
OVER = parse((SAMPLES / "response_4_overpromise.md").read_text())

R3 = "Integration with our **existing PostgreSQL inventory database** — no migration to a new database."
BUDGET = "€80,000–€120,000 total, including first year of support."
P_MIGRATE = "we recommend migrating away from your current PostgreSQL database to our proprietary cloud data platform"
P_PRICE_OVER = "Total project cost: **€98,000**"
INVENTED = "The vendor guarantees 99.99% uptime with 24/7 phone support."


# ---- normalize -------------------------------------------------------------------------


def test_normalize_strips_markdown_quotes_dashes_markers_and_whitespace():
    assert normalize("**Bold** and _it_ and `code`") == "bold and it and code"
    assert normalize("“curly” ‘quotes’ – and — dashes") == "\"curly\" 'quotes' - and - dashes"
    assert normalize("- item one\n1. item two\n> quoted") == "item one item two quoted"
    assert normalize("  many\n\n  spaces\tand nbsp ") == "many spaces and nbsp"
    assert normalize(None) == "" and normalize("") == ""


# ---- verify ----------------------------------------------------------------------------


def test_verbatim_in_claimed_section_is_verified():
    assert verify(R3, RFP, "§2") == ("verified", "§2")
    assert verify(R3, RFP, "Requirements") == ("verified", "§2")
    assert verify("no migration to a new database", RFP, "§2 Requirements") == ("verified", "§2")


def test_verbatim_without_a_claim_is_verified_and_located():
    assert verify(BUDGET, RFP) == ("verified", "§3")
    assert verify("€80,000-€120,000 total", RFP, None) == ("verified", "§3")  # straight dash


def test_formatting_differences_do_not_break_verification():
    assert (
        verify("integration with our existing postgresql inventory database", RFP, "§2")[0]
        == "verified"
    )
    assert verify(P_PRICE_OVER, OVER, "§4")[0] == "verified"
    assert verify("Total project cost: €98,000", OVER, "Pricing")[0] == "verified"


def test_verbatim_but_wrong_section_is_fuzzy_with_corrected_location():
    assert verify(P_MIGRATE, OVER, "§4") == ("fuzzy", "§2")  # it is in Proposed Solution
    assert verify(P_MIGRATE, OVER, "no such section") == ("fuzzy", "§2")


def test_light_paraphrase_is_fuzzy_short_paraphrase_is_not():
    status, section = verify(
        "we recommend migrating away from your existing PostgreSQL database to our proprietary cloud data platform",
        OVER,
        "§2",
    )
    assert status == "fuzzy" and section == "§2"
    assert verify("€89,000", OVER, "§4") == ("unverified", None)


def test_invented_and_empty_quotes_are_unverified():
    assert verify(INVENTED, WEAK, "§1") == ("unverified", None)
    assert verify(INVENTED, WEAK) == ("unverified", None)
    assert verify(None, WEAK) == ("unverified", None)
    assert verify("   ", WEAK, "§1") == ("unverified", None)


# ---- ground_extraction -----------------------------------------------------------------


def _extraction() -> RfpExtraction:
    return RfpExtraction(
        requirements=[
            Requirement(
                id="r3", label="Keep PostgreSQL", rfpQuote=R3, section="Background"
            ),  # wrong claim
            Requirement(id="r8", label="Budget", rfpQuote=BUDGET, section=None),
            Requirement(id="r9", label="Uptime", rfpQuote=INVENTED, section="§2"),
        ],
        constraints=[
            Constraint(
                id="c1", kind="TECHNOLOGY", label="No DB migration", rfpQuote=R3, section="§2"
            ),
            Constraint(
                id="c2",
                kind="BUDGET",
                label="Budget ceiling",
                rfpQuote="€500,000 hard cap",
                section="§3",
            ),
        ],
    )


def test_ground_extraction_sets_status_corrects_sections_and_drops_invented(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(config, "DROP_UNGROUNDED", True)
    ext, stats = ground_extraction(_extraction(), RFP)
    assert [r.id for r in ext.requirements] == ["r3", "r8"]
    assert ext.requirements[0].grounding == "fuzzy" and ext.requirements[0].section == "§2"
    assert ext.requirements[1].grounding == "verified" and ext.requirements[1].section == "§3"
    assert [c.id for c in ext.constraints] == ["c1"] and ext.constraints[0].grounding == "verified"
    assert stats == GroundingStats(dropped=2, fuzzy=1)


def test_ground_extraction_keeps_and_flags_when_not_dropping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DROP_UNGROUNDED", False)
    ext, stats = ground_extraction(_extraction(), RFP)
    assert [r.id for r in ext.requirements] == ["r3", "r8", "r9"]
    assert ext.requirements[2].grounding == "unverified" and ext.requirements[2].section == "§2"
    assert stats.dropped == 0


# ---- ground_scoring --------------------------------------------------------------------


def _cov(
    rid: str,
    status: CoverageStatus,
    section: str | None,
    quote: str | None,
    explanation: str | None = "e",
    fix: str | None = "f",
) -> CoverageItem:
    return CoverageItem(
        requirementId=rid,
        status=status,
        proposalSection=section,
        proposalQuote=quote,
        explanation=explanation,
        fix=fix,
    )


def _score(cid: str, score: int | None = 3, **kw) -> CriterionScore:
    kw.setdefault("weaknesses", "w")
    return CriterionScore(id=cid, score=score, **kw)  # type: ignore[arg-type]


def _llm() -> ScoreLlmOutput:
    return ScoreLlmOutput(
        coverage=[
            _cov("r3", "CONTRADICTED", "§2", P_MIGRATE),
            _cov("r8", "ADDRESSED", "§4", None, None, None),  # no quote: nothing to verify
            _cov("r6", "MISSING", None, None, "no SLA", "add one"),
            _cov("r4", "PARTIAL", "§2", INVENTED),
            _cov("r99", "ADDRESSED", "§1", None),  # unknown requirement id
            _cov("r1", "ADDRESSED", "Pricing", None, None, None),  # label, not id → canonicalised
        ],
        constraintViolations=[
            ConstraintViolation(
                constraintId="c1",
                proposalSection="§1",
                proposalQuote=P_MIGRATE,
                violation="v",
                severity="HIGH",
                fix="f",
            ),
            ConstraintViolation(
                constraintId="c1",
                proposalSection="§2",
                proposalQuote=INVENTED,
                violation="v",
                severity="LOW",
                fix="f",
            ),
            ConstraintViolation(
                constraintId="c77",
                proposalSection="§2",
                proposalQuote=P_MIGRATE,
                violation="unknown id",
                severity="LOW",
                fix="f",
            ),
        ],
        findings=[
            Finding(
                type="UNREALISTIC_TIMELINE",
                severity="HIGH",
                location="§4",
                proposalQuote="within **8 weeks**",
                explanation="e",
                fix="f",
            ),
            Finding(
                type="OVERCOMMIT",
                severity="LOW",
                location="§5",
                proposalQuote=INVENTED,
                explanation="e",
                fix="f",
            ),
            Finding(
                type="SCOPE_CREEP",
                severity="MEDIUM",
                location="§3",
                proposalQuote="8 weeks",
                explanation="dup",
                fix="f",
            ),
        ],
        scores=[
            _score(c)
            for c in CRITERIA
            if c not in ("pricing_clarity", "risk_transparency")  # risk omitted by the model
        ]
        + [
            _score(
                "pricing_clarity",
                4,
                citations=[
                    Citation(source="proposal", section="Pricing", quote=None),
                    Citation(source="rfp", section="§3", quote=None),
                    Citation(source="proposal", section="§99", quote=None),  # points nowhere
                    Citation(source="proposal", section="§4", quote=None),  # duplicate of the first
                ],
            ),
            _score("problem_understanding", 1, weaknesses="duplicate, must be ignored"),
        ],
    )


def _ext() -> RfpExtraction:
    return RfpExtraction(
        requirements=[
            Requirement(id=i, label=i, rfpQuote="x") for i in ("r1", "r3", "r4", "r6", "r8")
        ],
        constraints=[Constraint(id="c1", kind="TECHNOLOGY", label="c", rfpQuote="x")],
    )


def test_ground_scoring_drops_unverified_corrects_locations_and_completes_scores(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(config, "DROP_UNGROUNDED", True)
    llm, stats = ground_scoring(_llm(), _ext(), RFP, OVER)

    # coverage: invented r4 dropped, unknown r99 dropped; quote-less items keep grounding None
    assert [c.requirementId for c in llm.coverage] == ["r3", "r8", "r6", "r1"]
    r3, r8, r6, r1 = llm.coverage
    assert r3.grounding == "verified" and r3.proposalSection == "§2"
    assert r8.grounding is None and r8.proposalSection == "§4"
    assert r6.grounding is None and r6.proposalQuote is None and r6.proposalSection is None
    assert r1.grounding is None and r1.proposalSection == "§4"  # "Pricing" → §4

    # violations: wrong section → fuzzy + corrected; invented → dropped; unknown id → dropped
    assert len(llm.constraintViolations) == 1
    v = llm.constraintViolations[0]
    assert v.grounding == "fuzzy" and v.proposalSection == "§2"

    # scores: one per criterion in CRITERIA order, labels filled, first occurrence wins
    assert [s.id for s in llm.scores] == CRITERIA
    by_id = {s.id: s for s in llm.scores}
    assert by_id["problem_understanding"].score == 3
    assert by_id["risk_transparency"].score is None and "no score" in (
        by_id["risk_transparency"].note or ""
    )
    assert by_id["pricing_clarity"].label == "Pricing Clarity"
    # citations: label canonicalised, dangling pointer dropped, duplicate collapsed
    assert [(c.source, c.section, c.grounding) for c in by_id["pricing_clarity"].citations] == [
        ("proposal", "§4", "verified"),
        ("rfp", "§3", "verified"),
    ]
    # completeness is computed, whatever the model said: r1 1 + r3 0 + r4 0 + r6 0 + r8 1 = 2/5
    comp = by_id["completeness"]
    assert comp.score == 3 and comp.note and comp.note.startswith("computed from coverage: 2/5")
    assert [c.section for c in comp.citations] == ["§4"]

    # findings: formatting-only difference verified but relocated (§3 Timeline, not §4);
    # invented dropped; "8 weeks" is a substring of the first in the same section → deduped
    assert len(llm.findings) == 1
    assert llm.findings[0].type == "UNREALISTIC_TIMELINE"
    assert llm.findings[0].grounding == "fuzzy" and llm.findings[0].location == "§3"

    # dropped: coverage r4, violation, citation §99, finding INVENTED; fuzzy: violation, finding
    assert stats == GroundingStats(dropped=4, fuzzy=2)


def test_ground_scoring_keeps_quotes_when_not_dropping_but_never_dangling_pointers(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(config, "DROP_UNGROUNDED", False)
    llm, stats = ground_scoring(_llm(), _ext(), RFP, OVER)
    assert [c.requirementId for c in llm.coverage] == [
        "r3",
        "r8",
        "r6",
        "r4",
        "r1",
    ]  # r99 still gone
    assert llm.coverage[3].grounding == "unverified"
    assert len(llm.constraintViolations) == 2
    assert [f.type for f in llm.findings] == [
        "UNREALISTIC_TIMELINE",
        "OVERCOMMIT",
    ]  # dup still removed
    assert llm.findings[1].grounding == "unverified" and llm.findings[1].location == "§5"
    pricing = next(s for s in llm.scores if s.id == "pricing_clarity")
    assert len(pricing.citations) == 2  # a pointer to a non-existent section is never shown
    assert stats.dropped == 1


def test_citation_quotes_are_verified_like_any_other_quote(monkeypatch: pytest.MonkeyPatch):
    """A score citation quotes the words that justify it: verbatim in the claimed section →
    verified; verbatim elsewhere → fuzzy and relocated; invented → dropped; a quote-less
    pointer stays a pointer; duplicates after normalisation collapse."""
    monkeypatch.setattr(config, "DROP_UNGROUNDED", True)
    stats = GroundingStats()
    cits = [
        Citation(source="proposal", section="§4", quote=P_PRICE_OVER),
        Citation(source="proposal", section="§2", quote=P_PRICE_OVER),  # wrong section
        Citation(source="proposal", section="§4", quote=INVENTED),
        Citation(source="rfp", section="§3", quote=None),
        Citation(source="proposal", section="Pricing", quote="total project cost: €98,000"),
    ]
    kept = _ground_citations(cits, RFP, OVER, stats)
    assert [(c.source, c.section, c.grounding) for c in kept] == [
        ("proposal", "§4", "verified"),
        ("rfp", "§3", "verified"),
    ]
    assert stats == GroundingStats(dropped=1, fuzzy=1)
