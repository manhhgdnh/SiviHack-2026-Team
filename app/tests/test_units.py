"""Acceptance checks from the BACKEND.md cards, runnable offline with a fake provider.

uv run pytest
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import config, pipeline
from app.aggregate import normalize_weights, prioritize_coverage, weighted_overall
from app.grounding import ground_result, is_grounded
from app.llm import LlmProvider, call_json
from app.main import app
from app.schema import (
    CRITERIA,
    CoverageItem,
    CriterionScore,
    RfpExtraction,
    ScoreLlmOutput,
    ScoringMeta,
    ScoringResult,
)
from app.splitter import section_of, split_sections

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
RFP = (SAMPLES / "rfp_nordframe.md").read_text()
WEAK = (SAMPLES / "response_1_weak.md").read_text()

# Verbatim quotes, written on one line although the source wraps them.
R1 = "A **web-based dashboard** showing real-time inventory levels across all 6 warehouses."
R3 = "Integration with our **existing PostgreSQL inventory database** — no migration to a new database."
R6 = "**Support & maintenance terms** after go-live (response times, SLAs)."
BUDGET = "€80,000–€120,000 total, including first year of support."
P_DASH = "We will build a cloud-based dashboard that displays inventory data in real time."
P_PRICE = "Pricing will be provided upon further discussion of detailed requirements, and will depend on final scope."
P_LOGIN = "Secure login for different users"
INVENTED = "The vendor guarantees 99.99% uptime with 24/7 phone support."


def _scores(values: dict[str, int] | None = None) -> list[dict[str, Any]]:
    values = values or {}
    return [
        {
            "id": c,
            "label": c.replace("_", " "),
            "score": values.get(c, 3),
            "rationale": "because",
            "evidenceQuote": P_DASH if c == "problem_understanding" else None,
            "source": "proposal" if c == "problem_understanding" else None,
        }
        for c in CRITERIA
    ]


EXTRACT = {
    "requirements": [
        {"id": "r1", "label": "Web dashboard", "rfpQuote": R1, "section": None},
        {"id": "r3", "label": "Keep PostgreSQL", "rfpQuote": R3, "section": "made up"},
        {"id": "r6", "label": "Support terms", "rfpQuote": R6, "section": None},
        {"id": "r8", "label": "Budget", "rfpQuote": BUDGET, "section": None},
    ]
}
SCORE = {
    "coverage": [
        {
            "requirementId": "r1",
            "status": "ADDRESSED",
            "proposalQuote": P_DASH,
            "explanation": "dashboard promised",
            "fix": "none",
        },
        {
            "requirementId": "r3",
            "status": "PARTIAL",
            "proposalQuote": INVENTED,
            "explanation": "cloud only",
            "fix": "state PostgreSQL stays",
        },
        {
            "requirementId": "r6",
            "status": "MISSING",
            "proposalQuote": None,
            "explanation": "no SLA anywhere",
            "fix": "add Support & Maintenance section",
        },
        {
            "requirementId": "r8",
            "status": "PARTIAL",
            "proposalQuote": P_PRICE,
            "explanation": "deferred",
            "fix": "give a range inside €80k–120k",
        },
    ],
    "scores": _scores({"pricing_clarity": 1, "timeline_clarity": 1}),
    "risks": [
        {
            "type": "OVERCOMMIT",
            "proposalQuote": P_LOGIN,
            "rfpQuote": None,
            "explanation": "vague",
            "severity": "LOW",
        },
        {
            "type": "CONTRADICTION",
            "proposalQuote": INVENTED,
            "rfpQuote": None,
            "explanation": "not in the text",
            "severity": "HIGH",
        },
    ],
}


class FakeProvider(LlmProvider):
    """Answers the extract prompt and the score prompt with canned JSON; records calls."""

    name = "fake"
    model = "fake-model"

    def __init__(self, extract: str = json.dumps(EXTRACT), score: str = json.dumps(SCORE)):
        self.extract, self.score = extract, score
        self.calls: list[str] = []

    async def complete(self, prompt: str, temperature: float, json_mode: bool, schema=None) -> str:
        self.calls.append(prompt)
        return self.extract if prompt.startswith("You extract") else self.score


class FlakyProvider(LlmProvider):
    """Returns garbage `bad` times, then a valid fenced answer."""

    name = "flaky"
    model = "flaky-model"

    def __init__(self, bad: int):
        self.bad = bad
        self.calls: list[str] = []

    async def complete(self, prompt: str, temperature: float, json_mode: bool, schema=None) -> str:
        self.calls.append(prompt)
        if len(self.calls) <= self.bad:
            return '```json\n{"requirements": [{"id": 1'
        return "```json\n" + json.dumps(EXTRACT) + "\n```"


# ---- §8 schema ---------------------------------------------------------------------------


def test_schema_parses_and_rejects_out_of_range():
    out = ScoreLlmOutput.model_validate_json(json.dumps(SCORE))
    assert len(out.scores) == 7 and out.coverage[2].proposalQuote is None
    bad = json.loads(json.dumps(SCORE))
    bad["scores"][0]["score"] = 6
    with pytest.raises(ValidationError):
        ScoreLlmOutput.model_validate_json(json.dumps(bad))
    bad = json.loads(json.dumps(SCORE))
    bad["coverage"][0]["status"] = "KINDA"
    with pytest.raises(ValidationError):
        ScoreLlmOutput.model_validate_json(json.dumps(bad))


# ---- §11 splitter ------------------------------------------------------------------------


def test_split_sections_preserves_order_and_labels():
    secs = split_sections(RFP)
    headers = [s["header"] for s in secs]
    assert headers == [
        "Request for Proposal — Warehouse Inventory Dashboard",
        "Background",
        "Requirements",
        "Budget",
        "Timeline",
        "Decision Date",
    ]
    assert secs[0]["level"] == 1 and secs[1]["level"] == 2
    assert "NordFrame Logistics operates 6 regional warehouses" in secs[1]["body"]
    assert "€80,000" in secs[3]["body"] and "€80,000" not in secs[2]["body"]
    doc = "intro text\n\n# A\nbody a\n## B\nbody b"
    assert [s["header"] for s in split_sections(doc)] == ["preamble", "A", "B"]


def test_section_of_locates_a_quote():
    assert section_of(RFP, "no migration to a new database") == "Requirements"
    assert section_of(RFP, BUDGET) == "Budget"
    assert section_of(RFP, INVENTED) is None
    assert section_of(RFP, None) is None


# ---- §12 grounding -----------------------------------------------------------------------


def test_is_grounded_cases():
    assert is_grounded(R1, RFP)  # wrapped in the source, one line here
    assert is_grounded("  integration WITH our **Existing postgresql", RFP)  # case + spaces
    assert not is_grounded(INVENTED, WEAK)
    assert not is_grounded(None, WEAK) and not is_grounded("", WEAK)


def test_ground_result_flags_and_missing_is_kept(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DROP_UNGROUNDED", True)
    llm = ScoreLlmOutput.model_validate(SCORE)
    reqs = RfpExtraction.model_validate(EXTRACT).requirements
    llm, reqs, dropped = ground_result(llm, reqs, RFP, WEAK)
    assert all(r.grounded for r in reqs)
    assert [c.requirementId for c in llm.coverage] == ["r1", "r6", "r8"]  # invented r3 dropped
    assert next(c for c in llm.coverage if c.status == "MISSING").grounded is False
    assert [k.type for k in llm.risks] == ["OVERCOMMIT"]
    assert dropped == 2
    assert next(s for s in llm.scores if s.id == "problem_understanding").grounded


# ---- §13 aggregate -----------------------------------------------------------------------


def test_weights_and_ordering():
    scores = [CriterionScore.model_validate(s) for s in _scores({"pricing_clarity": 1})]
    equal = normalize_weights(None)
    assert set(equal) == set(CRITERIA) and weighted_overall(scores, equal) == round(19 / 7, 2)
    heavier = normalize_weights({"pricing_clarity": 3})
    assert weighted_overall(scores, heavier) < weighted_overall(scores, equal)
    assert weighted_overall([], equal) == 0.0
    cov = [CoverageItem.model_validate(c) for c in SCORE["coverage"]]
    cov.append(CoverageItem(requirementId="r9", status="CONTRADICTED", explanation="x", fix="y"))
    assert [c.status for c in prioritize_coverage(cov, equal)] == [
        "CONTRADICTED",
        "MISSING",
        "PARTIAL",
        "PARTIAL",
        "ADDRESSED",
    ]


# ---- §10 call_json -----------------------------------------------------------------------


def test_call_json_retries_once_then_raises():
    p = FlakyProvider(bad=1)
    out = asyncio.run(call_json(p, "You extract ...", RfpExtraction))
    assert len(out.requirements) == 4 and len(p.calls) == 2
    assert "previous output was invalid" in p.calls[1]
    with pytest.raises(ValidationError):
        asyncio.run(call_json(FlakyProvider(bad=2), "You extract ...", RfpExtraction))


# ---- §15 pipeline ------------------------------------------------------------------------


def test_pipeline_end_to_end_with_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(config, "USE_CACHE", True)
    monkeypatch.setattr(config, "DROP_UNGROUNDED", False)
    p = FakeProvider()

    first = asyncio.run(pipeline.score_proposal(RFP, WEAK, {"pricing_clarity": 2}, provider=p))
    assert isinstance(first, ScoringResult)
    assert first.meta.cacheHit is False and len(p.calls) == 2
    assert first.weights["pricing_clarity"] == 2.0 and len(first.weights) == 7
    assert first.overall == round((3 * 5 + 1 * 2 + 1) / (6 + 2), 2)
    assert [c.status for c in first.coverage] == ["MISSING", "PARTIAL", "PARTIAL", "ADDRESSED"]
    assert first.meta.ungroundedDropped == 0 and len(first.risks) == 2
    assert first.risks[0].severity == "HIGH"
    by_id = {r.id: r for r in first.requirements}
    assert by_id["r3"].section == "Requirements"  # deterministic label beats "made up"
    assert by_id["r8"].section == "Budget"
    assert all(r.grounded for r in first.requirements)
    assert (tmp_path / "cache").exists() and len(list((tmp_path / "cache").glob("*.json"))) == 1

    second = asyncio.run(pipeline.score_proposal(RFP, WEAK, provider=p))
    assert second.meta.cacheHit is True and len(p.calls) == 3  # extraction skipped
    assert second.requirements[1].section == "Requirements"


# ---- §16 routes --------------------------------------------------------------------------


def test_routes(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}
    assert client.post("/score", json={"rfp": "  ", "proposal": "x"}).status_code == 400

    async def fake_score(rfp, proposal, weights=None):
        return ScoringResult(
            overall=1.7,
            weights=normalize_weights(weights),
            scores=[],
            coverage=[],
            risks=[],
            requirements=[],
            meta=ScoringMeta(model="m", temperature=0.1, durationMs=1, ungroundedDropped=0),
        )

    monkeypatch.setattr("app.main.score_proposal", fake_score)
    r = client.post("/score", json={"rfp": "r", "proposal": "p", "weights": {"completeness": 2}})
    assert r.status_code == 200 and r.json()["overall"] == 1.7
    assert r.json()["weights"]["completeness"] == 2.0

    async def boom(rfp, proposal, weights=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("app.main.score_proposal", boom)
    r = client.post("/score", json={"rfp": "r", "proposal": "p"})
    assert r.status_code == 500 and "ollama down" in r.json()["detail"]
