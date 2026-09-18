"""Record Gemini's answers for the sample set and hand the results to the frontend.

    uv run --env-file .env python tests/record_fixtures.py [--force]

Runs the 4 samples against the RFP plus one proposal-only run through the recording
provider (cache off, split mode), asserts the regression criteria, writes
tests/fixtures/replay/<sha16>.json for every prompt that had no recording, and writes the
full ScoringResult of each run to frontend/src/api/fixtures/results/{weak, medium, strong,
overpromise, no-rfp}.json. Prompts that already have a recording cost nothing, so this is
safe to re-run at any time; --force deletes the recordings first (only for a model change).
"""

import asyncio
import shutil
import sys
from pathlib import Path

from regression import RESPONSES, check, load, row

from app import config, usage
from app.llm import GeminiProvider
from app.pipeline import score_proposal
from app.replay import DEFAULT_DIR, RecordingProvider
from app.schema import ScoringResult

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "frontend" / "src" / "api" / "fixtures" / "results"
NAMES = dict(zip(RESPONSES, ["weak", "medium", "strong", "overpromise"], strict=True))
NO_RFP_SAMPLE = "response_2_medium.md"


def completeness_score(r: ScoringResult) -> int | None:
    return next(s.score for s in r.scores if s.id == "completeness")


async def main(force: bool) -> int:
    config.USE_CACHE = False  # the recorder is the only memory this run has
    config.SPLIT_CALLS = "true"  # record what Gemini runs in the demo
    if force:
        shutil.rmtree(DEFAULT_DIR, ignore_errors=True)
    provider = RecordingProvider(GeminiProvider(), DEFAULT_DIR)
    before = usage.total_usd()
    rfp, docs = load(ROOT / "sample_data")
    RESULTS.mkdir(parents=True, exist_ok=True)
    results: dict[str, ScoringResult] = {}
    for name in RESPONSES:
        results[name] = r = await score_proposal(rfp, docs[name], provider=provider)
        (RESULTS / f"{NAMES[name]}.json").write_text(r.model_dump_json(indent=2))
        print(row(name, r))
    no_rfp = await score_proposal("", docs[NO_RFP_SAMPLE], provider=provider)
    (RESULTS / "no-rfp.json").write_text(no_rfp.model_dump_json(indent=2))
    print(row("no-rfp (medium)", no_rfp))

    failures = check(results)
    if no_rfp.requirements or completeness_score(no_rfp) is not None:
        failures.append("no-rfp run has requirements or a completeness score")
    total = len(list(DEFAULT_DIR.glob("*.json")))
    print(
        f"\n{len(provider.recorded)} new recordings ({total} total in {DEFAULT_DIR}); "
        f"spent ${usage.total_usd() - before:.3f}; total on this machine ${usage.total_usd():.3f}"
    )
    for f in failures:
        print(f"FAIL  {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    from app.logs import configure

    configure()
    sys.exit(asyncio.run(main("--force" in sys.argv)))
