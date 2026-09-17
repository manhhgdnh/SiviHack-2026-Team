"""Regression check + demo fallback (BACKEND.md §19). Plain asyncio, no framework.

Runs the 4 sample responses against the sample RFP, prints a table, asserts
weak < medium < strong and that the overpromising one is caught, and saves every
ScoringResult to data/cache/<name>.json (hand one to the frontend as the sample result).

    uv run --env-file .env python tests/regression.py [SAMPLES_DIR]
    docker compose exec backend python tests/regression.py
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
    counts = " ".join(f"{s[:4]}={sum(1 for c in r.coverage if c.status == s)}" for s in STATUSES)
    return f"{name:<28} {r.overall:>5.2f}  {counts}  risks={len(r.risks)}  {r.meta.durationMs}ms"


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
    if not (weak.overall < medium.overall < strong.overall):
        failures.append(
            f"separation broken: weak={weak.overall} medium={medium.overall} strong={strong.overall}"
        )
    if not any(c.status == "CONTRADICTED" for c in over.coverage):
        failures.append("overpromise has no CONTRADICTED coverage item")
    if not over.risks:
        failures.append("overpromise has no risk finding")

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
