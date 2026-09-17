"""Regression check + demo fallback. Plain asyncio, no framework; needs a reachable LLM.

Runs the 4 sample responses against the sample RFP, prints a table, asserts
weak < medium < strong and that the overpromising one is caught by a constraint violation,
and saves every ScoringResult to data/cache/<name>.json (hand one to the frontend as the
sample result).

    uv run --env-file .env python tests/regression.py [SAMPLES_DIR]
    docker compose exec backend python tests/regression.py /sample_data
"""

import asyncio
import sys
from pathlib import Path

from app.pipeline import CACHE, score_proposal
from app.schema import ScoringResult

# Repo-root sample_data/ locally; compose mounts the same folder at /sample_data.
DEFAULT_SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
RFP = "rfp_nordframe.md"
RESPONSES = [
    "response_1_weak.md",
    "response_2_medium.md",
    "response_3_strong.md",
    "response_4_overpromise.md",
]
STATUSES = ["ADDRESSED", "PARTIAL", "MISSING", "CONTRADICTED"]


def _row(name: str, r: ScoringResult) -> str:
    overall = f"{r.overall:>5.2f}" if r.overall is not None else " none"
    counts = " ".join(f"{s[:4]}={sum(1 for c in r.coverage if c.status == s)}" for s in STATUSES)
    flags = " PARTIAL" if r.partial else ""
    return (
        f"{name:<28} {overall}  {counts}  violations={len(r.constraintViolations)} "
        f"findings={len(r.findings)} dropped={r.meta.ungroundedDropped} "
        f"fuzzy={r.meta.fuzzyMatched}  {r.meta.mode} calls={r.meta.llmCalls} "
        f"cut={r.meta.truncated}  {r.meta.durationMs}ms{flags}"
    )


async def main(samples: Path) -> int:
    rfp = (samples / RFP).read_text()
    results: dict[str, ScoringResult] = {}
    print(f"samples: {samples}")
    for name in RESPONSES:
        results[name] = await score_proposal(rfp, (samples / name).read_text())
        CACHE.mkdir(parents=True, exist_ok=True)
        out = CACHE / f"{Path(name).stem}.json"
        out.write_text(results[name].model_dump_json(indent=2))
        print(_row(name, results[name]))

    weak, medium, strong, over = (results[n] for n in RESPONSES)
    failures: list[str] = []
    for name, r in results.items():
        if r.error:
            failures.append(f"{name}: {r.error}")
        for w in r.warnings:
            print(f"warn  {name}: {w}")
    scores = [weak.overall, medium.overall, strong.overall]
    if any(s is None for s in scores):
        failures.append(f"an overall is missing: weak/medium/strong = {scores}")
    elif not (scores[0] < scores[1] < scores[2]):  # type: ignore[operator]
        failures.append(
            f"separation broken: weak={scores[0]} medium={scores[1]} strong={scores[2]}"
        )
    if not over.constraintViolations:
        failures.append("overpromise has no constraint violation (PostgreSQL migration)")
    if not any(c.status == "CONTRADICTED" for c in over.coverage):
        print("note  overpromise has no CONTRADICTED coverage item (violation caught it instead)")
    if not over.findings:
        failures.append("overpromise has no finding (8-week timeline / scope creep)")
    if strong.constraintViolations:
        failures.append(
            f"strong proposal has {len(strong.constraintViolations)} constraint violation(s)"
        )

    print()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1
    print(f"OK    4 results written to {CACHE}/")
    return 0


if __name__ == "__main__":
    samples = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLES
    sys.exit(asyncio.run(main(samples)))
