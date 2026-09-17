"""What the frontend ships must be what the backend produces: sample copies byte-identical,
recorded ScoringResult JSONs valid and equal to a replay run, requirements.txt current."""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from regression import RESPONSES, load

from app import config, pipeline
from app.replay import ReplayProvider
from app.schema import ScoringResult

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample_data"
COPIES = ROOT / "frontend" / "src" / "api" / "fixtures" / "samples"
RESULTS = ROOT / "frontend" / "src" / "api" / "fixtures" / "results"
NAMES = dict(zip(RESPONSES, ["weak", "medium", "strong", "overpromise"], strict=True))
EXPORT = [
    "uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--no-header",
    "--format", "requirements-txt",
]  # fmt: skip


def test_frontend_sample_copies_match_sample_data():
    ours = {p.name: p.read_bytes() for p in SAMPLES.glob("*.md")}
    theirs = {p.name: p.read_bytes() for p in COPIES.glob("*.md")}
    assert ours.keys() == theirs.keys(), "cp sample_data/*.md frontend/src/api/fixtures/samples/"
    for name, data in ours.items():
        assert theirs[name] == data, f"{name} differs: cp sample_data/{name} {COPIES}/"


recorded = pytest.mark.skipif(
    not (RESULTS / "weak.json").exists(), reason="run tests/record_fixtures.py"
)


@recorded
def test_result_fixtures_validate_and_match_a_replay_run(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "USE_CACHE", False)
    monkeypatch.setattr(config, "SPLIT_CALLS", "true")
    rfp, docs = load(SAMPLES)
    for name, stem in NAMES.items():
        shipped = ScoringResult.model_validate_json((RESULTS / f"{stem}.json").read_text())
        now = asyncio.run(pipeline.score_proposal(rfp, docs[name], provider=ReplayProvider()))
        assert shipped.model_dump(exclude={"meta"}) == now.model_dump(exclude={"meta"}), (
            f"{stem}.json is stale: run tests/record_fixtures.py"
        )
    no_rfp = ScoringResult.model_validate_json((RESULTS / "no-rfp.json").read_text())
    assert no_rfp.requirements == [] and no_rfp.coverage == []
    assert next(s for s in no_rfp.scores if s.id == "completeness").score is None
    over = ScoringResult.model_validate_json((RESULTS / "overpromise.json").read_text())
    assert over.constraintViolations and all(f.proposalQuote and f.fix for f in over.findings)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_requirements_txt_is_current():
    out = subprocess.run(EXPORT, cwd=ROOT / "app", check=True, capture_output=True, text=True)
    assert (ROOT / "requirements.txt").read_text() == out.stdout, "run: make requirements"
