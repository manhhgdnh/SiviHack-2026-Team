"""End-to-end through the pipeline with a canned provider: both scoring modes, events,
caching, no-RFP, per-group failure, truncation salvage."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from app import config, pipeline, usage
from app.llm import Completion, LlmProvider
from app.prompts import (
    GROUPS,
    PROMPT_VERSION,
    build_coverage_prompt,
    build_extract_prompt,
    build_group_prompt,
    build_score_prompt,
)
from app.schema import CRITERIA, CoverageLlmOutput, RfpExtraction, ScoringResult
from app.signals import compute_signals, render_signals
from app.splitter import parse

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
RFP = (SAMPLES / "rfp_nordframe.md").read_text()
OVER = (SAMPLES / "response_4_overpromise.md").read_text()

R1 = "A **web-based dashboard** showing real-time inventory levels across all 6 warehouses."
R3 = "Integration with our **existing PostgreSQL inventory database** — no migration to a new database."
R6 = "**Support & maintenance terms** after go-live (response times, SLAs)."
BUDGET = "€80,000–€120,000 total, including first year of support."
P_MIGRATE = "we recommend migrating away from your current PostgreSQL database to our proprietary cloud data platform"
P_SUPPORT = "one year of support"
P_WEEKS = "within **8 weeks**"
P_FORECAST = "predictive demand forecasting"
INVENTED = "The vendor guarantees 99.99% uptime with 24/7 phone support."

EXTRACT: dict[str, Any] = {
    "requirements": [
        {"id": "r1", "label": "Web dashboard", "rfpQuote": R1, "section": "§2"},
        {"id": "r3", "label": "Keep PostgreSQL", "rfpQuote": R3, "section": "made up"},
        {"id": "r6", "label": "Support terms", "rfpQuote": R6, "section": None},
        {"id": "r8", "label": "Budget", "rfpQuote": BUDGET, "section": "§3"},
    ],
    "constraints": [
        {
            "id": "c1",
            "kind": "TECHNOLOGY",
            "label": "No DB migration",
            "rfpQuote": "no migration to a new database",
            "section": "§2",
        },
        {
            "id": "c2",
            "kind": "BUDGET",
            "label": "Budget range",
            "rfpQuote": BUDGET,
            "section": "§3",
        },
    ],
    "suggestedWeights": [
        {"criterionId": "risk_transparency", "weight": 2, "reason": "RFP asks for risks explicitly"}
    ],
}


def _cov(rid, status, section, quote=None, explanation=None, fix=None) -> dict[str, Any]:
    return {
        "requirementId": rid,
        "status": status,
        "proposalSection": section,
        "proposalQuote": quote,
        "explanation": explanation,
        "fix": fix,
    }


def _score(cid, score, cits=()) -> dict[str, Any]:
    return {
        "id": cid,
        "score": score,
        "strengths": None,
        "weaknesses": "w",
        "citations": list(cits),
    }


def _finding(type_, sev, loc, quote) -> dict[str, Any]:
    return {
        "type": type_,
        "severity": sev,
        "location": loc,
        "proposalQuote": quote,
        "explanation": "e",
        "fix": "f",
    }


COVERAGE: dict[str, Any] = {
    "coverage": [
        _cov("r1", "ADDRESSED", "§2"),
        _cov(
            "r3",
            "CONTRADICTED",
            "§2",
            P_MIGRATE,
            "migrates away from PostgreSQL",
            "keep PostgreSQL",
        ),
        _cov("r6", "PARTIAL", "§4", P_SUPPORT, "no SLAs", "add SLAs"),
        _cov("r8", "ADDRESSED", "§4"),
    ],
    "constraintViolations": [
        {
            "constraintId": "c1",
            "proposalSection": "§2",
            "proposalQuote": P_MIGRATE,
            "violation": "migrates away from PostgreSQL",
            "severity": "HIGH",
            "fix": "drop the migration",
        },
    ],
}
GROUP_ANSWERS: dict[str, dict[str, Any]] = {
    "understanding": {
        "findings": [],
        "scores": [_score("problem_understanding", 2), _score("tone_persuasiveness", 3)],
    },
    "commercials": {
        "findings": [
            _finding("SCOPE_CREEP", "MEDIUM", "§1", P_FORECAST),
            _finding("UNREALISTIC_TIMELINE", "HIGH", "§3", P_WEEKS),
        ],
        "scores": [
            _score("scope_clarity", 3),
            _score(
                "pricing_clarity",
                4,
                [
                    {"source": "proposal", "section": "§4", "quote": None},
                    {"source": "rfp", "section": "§3", "quote": None},
                ],
            ),
            _score("timeline_clarity", 2, [{"source": "proposal", "section": "§3", "quote": None}]),
        ],
    },
    "risk": {
        "findings": [
            _finding("OVERCOMMIT", "LOW", "§5", INVENTED),
            _finding("UNREALISTIC_TIMELINE", "MEDIUM", "§3", "8 weeks"),
        ],
        "scores": [_score("risk_transparency", 1)],
    },
}
MERGED: dict[str, Any] = {
    **COVERAGE,
    "findings": [f for g in GROUP_ANSWERS.values() for f in g["findings"]],
    "scores": [s for g in GROUP_ANSWERS.values() for s in g["scores"]],
}
ANSWERS: dict[str, dict[str, Any]] = {
    "extract": EXTRACT,
    "coverage": COVERAGE,
    "merged": MERGED,
    **{f"group:{gid}": ans for gid, ans in GROUP_ANSWERS.items()},
}
# equal weights except risk ×2: (2 + 3 + 4 + 2 + completeness 4 + 3 + 1·2) / 8
# completeness: r1 1 + r3 0 + r6 0.5 + r8 1 = 2.5/4 → round(1 + 2.5) = 4
EXPECTED_OVERALL = round((2 + 3 + 4 + 2 + 4 + 3 + 1 * 2) / 8, 2)


def _kind(prompt: str) -> str:
    if prompt.startswith("You extract"):
        return "extract"
    if prompt.startswith("You check"):
        return "coverage"
    if prompt.startswith("You score"):
        m = re.search(r"Group id: (\w+)", prompt)
        assert m
        return f"group:{m.group(1)}"
    assert prompt.startswith("You are a senior"), prompt[:60]
    return "merged"


class FakeProvider(LlmProvider):
    """Answers each prompt kind with canned JSON; can fail or truncate chosen kinds."""

    name, model = "fake", "fake-model"  # not "gemini" → merged unless LLM_SPLIT_CALLS=true

    def __init__(self, fail: set[str] | None = None, truncate: set[str] | None = None):
        self.fail, self.truncate = set(fail or ()), set(truncate or ())
        self.calls: list[str] = []

    async def complete(
        self, prompt, schema, temperature, strict=False, reasoning=None
    ) -> Completion:
        kind = _kind(prompt)
        self.calls.append(kind)
        if kind in self.fail:
            return Completion("not json at all", False)
        text = json.dumps(ANSWERS[kind])
        if kind in self.truncate:
            # cut inside the scores array, right after the first score object: json_repair can
            # close it, so the answer survives with one score fewer
            first_end = text.index("}", text.index('"scores"')) + 1
            return Completion(text[:first_end], True)
        return Completion(text, False)


def _events(rfp: str, proposal: str, weights=None, provider=None) -> list[tuple[str, Any]]:
    async def collect():
        return [(e, p) async for e, p in pipeline.run(rfp, proposal, weights, provider)]

    return asyncio.run(collect())


EVENTS = ["sections", "requirements", "coverage", "scores", "findings", "done"]


def _stages(events: list[tuple[str, Any]]) -> list[str]:
    """The stage frames in order; progress notes are interleaved and checked separately."""
    return [e for e, _ in events if e != "progress"]


def _payloads(events: list[tuple[str, Any]]) -> list[Any]:
    return [p for e, p in events if e != "progress"]


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(pipeline, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(config, "USE_CACHE", True)
    monkeypatch.setattr(config, "DROP_UNGROUNDED", True)
    monkeypatch.setattr(config, "SPLIT_CALLS", "auto")
    return tmp_path / "cache"


@pytest.fixture
def split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SPLIT_CALLS", "true")


# ---- mode flag ---------------------------------------------------------------------------


def test_split_mode_follows_provider_unless_forced(monkeypatch: pytest.MonkeyPatch):
    p = FakeProvider()
    monkeypatch.setattr(config, "SPLIT_CALLS", "auto")
    assert pipeline.split_mode(p) is False
    p.name = "gemini"
    assert pipeline.split_mode(p) is True
    monkeypatch.setattr(config, "SPLIT_CALLS", "false")
    assert pipeline.split_mode(p) is False
    monkeypatch.setattr(config, "SPLIT_CALLS", "true")
    p.name = "ollama"
    assert pipeline.split_mode(p) is True


# ---- prompts -----------------------------------------------------------------------------


def test_prompts_carry_markers_context_and_reasoning_order():
    rdoc, pdoc = parse(RFP), parse(OVER)
    ext = RfpExtraction.model_validate(EXTRACT)
    cov = CoverageLlmOutput.model_validate(COVERAGE)
    sig = render_signals(compute_signals(pdoc), pdoc)

    e = build_extract_prompt(rdoc)
    assert "[§2 Requirements]" in e and "constraints[]" in e and "at most 20 words" in e

    c = build_coverage_prompt(ext, pdoc)
    assert c.startswith("You check") and "[§4 Pricing]" in c
    assert c.index("1. coverage[]") < c.index("2. constraintViolations[]")
    assert '"c1"' in c and "no migration to a new database" in c

    by_id = {g.id: g for g in GROUPS}
    gp = build_group_prompt(
        by_id["commercials"], ext, pdoc, cov.coverage, cov.constraintViolations, sig, None
    )
    assert gp.startswith("You score") and "Group id: commercials" in gp
    assert gp.index("1. findings[]") < gp.index("2. scores[]")
    assert "exactly 3 objects" in gp and "pricing_clarity ≤ 2" in gp
    assert "€98,000" in gp and "8 weeks" in gp  # signals
    assert "SCOPE_CREEP" in gp and "OVERCOMMIT" not in gp.split("RUBRIC")[0]  # owns its types only
    assert "r3 CONTRADICTED in §2" in gp and "VIOLATION c1 HIGH" in gp

    gu = build_group_prompt(
        by_id["understanding"], ext, pdoc, cov.coverage, cov.constraintViolations, None, rdoc
    )
    assert (
        "[§1 Background]" in gu and "problem_understanding ≤ 3" in gu and "PRE-COMPUTED" not in gu
    )

    gr = build_group_prompt(
        by_id["risk"], ext, pdoc, cov.coverage, cov.constraintViolations, None, None
    )
    assert "exactly 1 object," in gr and "Do not write fixes for missing" in gr

    m = build_score_prompt(ext, pdoc, sig)
    assert m.startswith("You are a senior")
    assert (
        m.index("1. coverage[]")
        < m.index("2. constraintViolations[]")
        < m.index("3. findings[]")
        < m.index("4. scores[]")
    )
    assert "exactly 6 objects" in m and "completeness is computed by code" in m
    empty = build_score_prompt(RfpExtraction(requirements=[], constraints=[]), pdoc, "none")
    assert "NO RFP WAS PROVIDED" in empty


# ---- merged mode -------------------------------------------------------------------------


def _check_full_result(done: ScoringResult, mode: str, calls: int) -> None:
    assert isinstance(done, ScoringResult) and done.partial is False and done.error is None
    assert done.warnings == [] and done.meta.mode == mode and done.meta.llmCalls == calls
    assert done.overall == EXPECTED_OVERALL and done.weights["risk_transparency"] == 2.0
    assert [s.id for s in done.scores] == CRITERIA
    comp = next(s for s in done.scores if s.id == "completeness")
    assert comp.score == 4 and comp.note and comp.note.startswith("computed from coverage")
    assert [c.status for c in done.coverage] == [
        "CONTRADICTED",
        "PARTIAL",
        "ADDRESSED",
        "ADDRESSED",
    ]
    assert done.coverage[0].grounding == "verified" and done.coverage[2].grounding is None
    assert [
        (v.constraintId, v.grounding, v.proposalSection) for v in done.constraintViolations
    ] == [("c1", "verified", "§2")]
    assert [f.type for f in done.findings] == [
        "UNREALISTIC_TIMELINE",
        "SCOPE_CREEP",
    ]  # invented dropped, "8 weeks" deduped
    pricing = next(s for s in done.scores if s.id == "pricing_clarity")
    assert [(c.source, c.section) for c in pricing.citations] == [("proposal", "§4"), ("rfp", "§3")]
    by_id = {r.id: r for r in done.requirements}
    assert by_id["r3"].section == "§2" and by_id["r3"].grounding == "fuzzy"  # "made up" corrected
    assert done.meta.ungroundedDropped == 1 and done.meta.fuzzyMatched == 1
    assert done.meta.truncated == 0 and done.meta.repaired == 0
    assert done.meta.model == "fake-model" and done.meta.promptVersion == PROMPT_VERSION
    assert done.signals.pricing.mentions[0].value == "€98,000"


def test_merged_mode_two_calls_events_in_order(cache: Path):
    p = FakeProvider()
    events = _events(RFP, OVER, {"risk_transparency": 2}, p)
    assert _stages(events) == EVENTS
    assert p.calls == ["extract", "merged"]
    sections, reqs, cov, scores, findings, done = _payloads(events)
    assert sections.rfp.count == 6 and sections.proposal.sections[4].header == "Pricing"
    assert [r.id for r in reqs.requirements] == [
        "r1",
        "r3",
        "r6",
        "r8",
    ] and reqs.extractCached is False
    assert [c.id for c in reqs.constraints] == ["c1", "c2"] and reqs.suggestedWeights[0].weight == 2
    assert [c.status for c in cov.coverage] == ["CONTRADICTED", "PARTIAL", "ADDRESSED", "ADDRESSED"]
    assert cov.constraintViolations[0].constraintId == "c1"
    assert scores.overall == EXPECTED_OVERALL and len(scores.scores) == 7
    assert [f.type for f in findings.findings] == ["UNREALISTIC_TIMELINE", "SCOPE_CREEP"]
    _check_full_result(done, "merged", 2)
    assert len(list(cache.glob("*.json"))) == 2


# ---- split mode --------------------------------------------------------------------------


def test_split_mode_runs_coverage_then_three_groups(cache: Path, split: None):
    p = FakeProvider()
    events = _events(RFP, OVER, {"risk_transparency": 2}, p)
    assert _stages(events) == EVENTS
    assert p.calls[:2] == ["extract", "coverage"]
    assert sorted(p.calls[2:]) == ["group:commercials", "group:risk", "group:understanding"]
    _check_full_result(events[-1][1], "split", 5)
    assert len(list(cache.glob("*.json"))) == 5


def test_split_mode_group_failure_nulls_only_that_groups_criteria(cache: Path, split: None):
    p = FakeProvider(fail={"group:commercials"})
    done = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert (
        p.calls.count("group:commercials") == 2 and len(p.calls) == 6
    )  # its strict retry failed too
    assert done.partial is True and done.error is None
    assert len(done.warnings) == 1 and "scoring group 'commercials' failed" in done.warnings[0]
    by_id = {s.id: s for s in done.scores}
    for cid in ("scope_clarity", "pricing_clarity", "timeline_clarity"):
        assert by_id[cid].score is None and "commercials" in (by_id[cid].note or "")
    assert by_id["problem_understanding"].score == 2 and by_id["completeness"].score == 4
    assert done.overall == round((2 + 4 + 3 + 1) / 4, 2)  # the six that were scored, minus three
    assert [f.type for f in done.findings] == [
        "UNREALISTIC_TIMELINE"
    ]  # risk group's "8 weeks" survives alone
    assert len(done.coverage) == 4 and len(done.constraintViolations) == 1


def test_split_mode_truncated_group_is_salvaged_and_flagged_even_from_cache(
    cache: Path, split: None
):
    p = FakeProvider(truncate={"group:commercials"})
    done = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 5  # salvaged, no retry
    assert done.partial is True and done.meta.truncated == 1 and done.meta.repaired == 1
    assert any("salvaged" in w for w in done.warnings)
    by_id = {s.id: s for s in done.scores}
    assert by_id["scope_clarity"].score == 3  # the one score that survived the cut
    assert by_id["pricing_clarity"].score is None and by_id["timeline_clarity"].score is None
    assert [f.type for f in done.findings] == [
        "UNREALISTIC_TIMELINE",
        "SCOPE_CREEP",
    ]  # findings came first, intact

    again = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 5 and again.meta.scoreCached is True
    assert again.partial is True and again.meta.truncated == 1  # the cache remembers the salvage


def test_coverage_call_failure_yields_partial_result_with_requirements(cache: Path, split: None):
    p = FakeProvider(fail={"coverage"})
    events = _events(RFP, OVER, provider=p)
    assert _stages(events) == ["sections", "requirements", "done"]
    assert p.calls == ["extract", "coverage", "coverage"]  # no groups without a triage
    done = events[-1][1]
    assert (
        done.partial is True
        and done.error
        and ("ValidationError" in done.error or "JSONDecodeError" in done.error)
    )
    assert [r.id for r in done.requirements] == ["r1", "r3", "r6", "r8"] and len(
        done.constraints
    ) == 2
    assert done.scores == [] and done.overall is None
    assert len(list(cache.glob("*.json"))) == 1


# ---- cache -------------------------------------------------------------------------------


def test_cache_serves_every_call_and_weights_are_not_in_the_key(cache: Path, split: None):
    p = FakeProvider()
    first = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 5

    again = asyncio.run(pipeline.score_proposal(RFP, OVER, {"pricing_clarity": 3}, provider=p))
    assert len(p.calls) == 5  # no LLM call: the slider is code only
    assert again.meta.extractCached and again.meta.scoreCached and again.meta.llmCalls == 0
    assert again.overall != first.overall and again.scores == first.scores

    # a different proposal reuses the RFP extraction only
    asyncio.run(pipeline.score_proposal(RFP, OVER + "\n\n## Extra\nmore", provider=p))
    assert len(p.calls) == 9 and "extract" not in p.calls[5:]


def test_extract_requirements_shares_the_cache_with_a_full_run(cache: Path):
    """POST /rfp/extract is call 1 alone; the full run that follows finds it in the cache."""
    p = FakeProvider()
    ev = asyncio.run(pipeline.extract_requirements(RFP, provider=p))
    assert p.calls == ["extract"] and ev.extractCached is False
    assert [r.id for r in ev.requirements] and ev.constraints and ev.suggestedWeights
    done = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert p.calls.count("extract") == 1 and done.meta.extractCached is True
    again = asyncio.run(pipeline.extract_requirements(RFP, provider=p))
    assert again.extractCached is True and p.calls.count("extract") == 1


def test_budget_guard_stops_a_real_call_but_not_a_cache_hit(
    cache: Path, split: None, monkeypatch: pytest.MonkeyPatch
):
    p = FakeProvider()
    asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))  # fills the cache: 5 calls
    monkeypatch.setattr(usage, "total_usd", lambda: 9.0)
    monkeypatch.setattr(config, "BUDGET_USD", 5.0)
    again = asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 5 and again.meta.scoreCached  # hits need no budget
    # a new proposal: extraction is cached, the coverage call is refused → partial, no call
    partial = asyncio.run(pipeline.score_proposal(RFP, OVER + "\n\n## More\nx", provider=p))
    assert partial.partial and "BudgetExceeded" in (partial.error or "") and len(p.calls) == 5
    # a new RFP: call 1 itself is refused → the run fails outright
    with pytest.raises(usage.BudgetExceeded):
        asyncio.run(pipeline.score_proposal(RFP + "\n\n## More\nx", OVER, provider=p))
    assert len(p.calls) == 5


def test_cache_key_includes_prompt_version_and_model(cache: Path, monkeypatch: pytest.MonkeyPatch):
    p = FakeProvider()
    asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    monkeypatch.setattr(pipeline, "PROMPT_VERSION", "test-bump")
    asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 4
    p.model = "other-model"
    asyncio.run(pipeline.score_proposal(RFP, OVER, provider=p))
    assert len(p.calls) == 6


# ---- no RFP ------------------------------------------------------------------------------


def test_without_rfp_completeness_is_null_not_zero(cache: Path):
    p = FakeProvider()
    events = _events("", OVER, provider=p)
    assert _stages(events) == EVENTS
    assert p.calls == ["merged"]  # no extraction call
    done = events[-1][1]
    assert done.requirements == [] and done.constraints == [] and done.coverage == []
    comp = next(s for s in done.scores if s.id == "completeness")
    assert comp.score is None and "no RFP" in (comp.note or "")
    assert done.overall == round((2 + 3 + 4 + 2 + 3 + 1) / 6, 2)
    assert done.sections.rfp.count == 0


def test_without_rfp_split_mode_skips_the_coverage_call(cache: Path, split: None):
    p = FakeProvider()
    done = asyncio.run(pipeline.score_proposal("", OVER, provider=p))
    assert sorted(p.calls) == ["group:commercials", "group:risk", "group:understanding"]
    assert done.coverage == [] and done.constraintViolations == []
    assert next(s for s in done.scores if s.id == "completeness").score is None


def test_call_1_failure_raises(cache: Path):
    class Broken(FakeProvider):
        async def complete(self, prompt, schema, temperature, strict=False, reasoning=None):
            raise RuntimeError("ollama down")

    with pytest.raises(RuntimeError, match="ollama down"):
        asyncio.run(pipeline.score_proposal(RFP, OVER, provider=Broken()))


def test_progress_notes_say_what_each_stage_is_doing(cache: Path, split: None, caplog):
    """Between the stage frames the pipeline narrates itself, and the same lines reach the log."""
    caplog.set_level(logging.INFO, logger="app.pipeline")
    events = _events(RFP, OVER, provider=FakeProvider())
    notes = [p for e, p in events if e == "progress"]
    assert [n.stage for n in notes[:3]] == ["requirements", "requirements", "coverage"]
    assert "asking the model" in notes[0].message and "Verified" in notes[1].message
    assert any("scoring 6 criteria in 3 parallel groups" in n.message for n in notes)
    assert {n.message.split(" ")[0] for n in notes if "scored:" in n.message} == {
        "understanding",
        "commercials",
        "risk",
    }
    assert notes[-1].stage == "findings" and "computing the overall" in notes[-1].message
    assert all(n.elapsedMs >= 0 for n in notes)
    # the run itself is one line of log per call and per stage, tagged with a run id
    lines = [r.getMessage() for r in caplog.records if r.name == "app.pipeline"]
    assert any("extract: calling fake" in line for line in lines)
    assert any("coverage: addressed=" in line for line in lines)
    assert any(" done in " in line and "overall=" in line for line in lines)
    tags = {line.split(" ")[0] for line in lines if line.startswith("[")}
    assert len(tags) == 1 and len(next(iter(tags))) == 6  # "[abcd]"
