"""Replay / record providers: hit, miss, fail switch, recording, provider switch, and the
regression criteria on the committed recordings (the regression run, at no cost)."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from regression import RESPONSES, check, load
from test_pipeline import FakeProvider

from app import config, llm, pipeline
from app.llm import Completion, GeminiProvider
from app.replay import DEFAULT_DIR, RecordingProvider, ReplayMiss, ReplayProvider, classify, key

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
EXTRACT_PROMPT = "You extract what a client asks for ... <<<rfp>>>"
COVERAGE_PROMPT = "You check a draft PROPOSAL ..."


def _write(d: Path, prompt: str, text: str, truncated: bool = False) -> None:
    d.mkdir(parents=True, exist_ok=True)
    rec = {"kind": classify(prompt), "text": text, "truncated": truncated}
    (d / f"{key(prompt)}.json").write_text(json.dumps(rec))


def test_replay_hit_returns_recorded_text_and_truncation(tmp_path: Path):
    _write(tmp_path, EXTRACT_PROMPT, '{"requirements": []}', truncated=True)
    c = asyncio.run(ReplayProvider(tmp_path).complete(EXTRACT_PROMPT, {}, 0.0))
    assert c == Completion('{"requirements": []}', True, None)  # no usage → no usage row


def test_replay_miss_raises_and_never_touches_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def never(req: httpx.Request) -> httpx.Response:
        pytest.fail("network")

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(never))
    with pytest.raises(ReplayMiss, match="extract"):
        asyncio.run(ReplayProvider(tmp_path).complete(EXTRACT_PROMPT, {}, 0.0))


def test_replay_fail_switch_answers_invalid_json_for_that_kind(tmp_path: Path):
    _write(tmp_path, COVERAGE_PROMPT, "{}")
    p = ReplayProvider(tmp_path, fail={"coverage"})
    assert asyncio.run(p.complete(COVERAGE_PROMPT, {}, 0.0)).text.startswith("not json")
    assert classify("You score a draft PROPOSAL ... Group id: risk.") == "group:risk"


def test_recorder_writes_one_file_per_prompt_and_reuses_it(tmp_path: Path):
    inner = FakeProvider()
    rec = RecordingProvider(inner, tmp_path)
    assert rec.name == "fake" and rec.model == "fake-model"
    first = asyncio.run(rec.complete(EXTRACT_PROMPT, {}, 0.0))
    again = asyncio.run(rec.complete(EXTRACT_PROMPT, {}, 0.0))
    assert first.text == again.text and inner.calls == ["extract"]  # second served from disk
    saved = json.loads((tmp_path / f"{key(EXTRACT_PROMPT)}.json").read_text())
    assert saved["kind"] == "extract" and saved["model"] == "fake-model"
    assert saved["prompt_head"] == EXTRACT_PROMPT[:80] and rec.recorded == ["extract"]


def test_replay_fail_yields_a_partial_result_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "USE_CACHE", False)
    monkeypatch.setattr(config, "SPLIT_CALLS", "true")
    rfp, docs = load(SAMPLES)
    over = docs[RESPONSES[3]]
    full = asyncio.run(
        pipeline.score_proposal(rfp, over, provider=RecordingProvider(FakeProvider(), tmp_path))
    )
    assert full.error is None and full.requirements
    done = asyncio.run(
        pipeline.score_proposal(rfp, over, provider=ReplayProvider(tmp_path, fail={"coverage"}))
    )
    assert done.partial and done.error and done.scores == []
    assert [r.id for r in done.requirements] == [r.id for r in full.requirements]


def test_get_provider_switch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "replay")
    assert isinstance(llm.get_provider(), ReplayProvider)
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "RECORD_DIR", "x")
    p = llm.get_provider()
    assert isinstance(p, RecordingProvider) and isinstance(p.inner, GeminiProvider)
    assert p.name == "gemini"


def test_split_mode_treats_replay_like_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SPLIT_CALLS", "auto")
    assert pipeline.split_mode(ReplayProvider()) is True


recorded = pytest.mark.skipif(
    not any(DEFAULT_DIR.glob("*.json")), reason="no recordings yet: run tests/record_fixtures.py"
)


@recorded
def test_recorded_samples_still_meet_the_regression_criteria(monkeypatch: pytest.MonkeyPatch):
    """weak < medium < strong, overpromise caught, strong clean: on the committed recordings."""
    monkeypatch.setattr(config, "USE_CACHE", False)
    monkeypatch.setattr(config, "SPLIT_CALLS", "true")
    rfp, docs = load(SAMPLES)
    results = {
        n: asyncio.run(pipeline.score_proposal(rfp, docs[n], provider=ReplayProvider()))
        for n in RESPONSES
    }
    assert check(results) == []
    assert all(r.meta.llmCalls == 5 and r.meta.mode == "split" for r in results.values())
