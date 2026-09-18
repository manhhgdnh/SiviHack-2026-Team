"""Regression check + demo fallback. Plain asyncio, no framework; needs a reachable LLM (or
the replay provider: LLM_PROVIDER=replay serves the recordings, and with USE_CACHE=true that
warms data/cache for the demo at no cost).

Runs the 4 sample responses against the sample RFP, prints a table, asserts
weak < medium < strong and that the overpromising one is caught by a constraint violation,
and saves every ScoringResult to data/cache/<name>.json.

    uv run --env-file .env python tests/regression.py [SAMPLES_DIR]
    docker compose exec backend python tests/regression.py /sample_data

`canonical`, `load`, `check` and `row` are shared with tests/record_fixtures.py and the
fixture tests, so every entry point sends the same text and applies the same criteria.
"""

import asyncio
import re
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
_BANNER = re.compile(r"^\s*\*\*Variant:", re.IGNORECASE)


def canonical(text: str) -> str:
    """Exactly what the frontend sends for a sample: the `**Variant: …**` fixture banner
    dropped (it announces the verdict inside the text under review) and trailing whitespace
    trimmed. Replay keys and cache keys hash the text, so every entry point must send this."""
    return "\n".join(line for line in text.split("\n") if not _BANNER.match(line)).rstrip()


def load(samples: Path) -> tuple[str, dict[str, str]]:
    rfp = canonical((samples / RFP).read_text())
    return rfp, {name: canonical((samples / name).read_text()) for name in RESPONSES}


def check(results: dict[str, ScoringResult]) -> list[str]:
    """The regression criteria as a list of failures (empty = OK)."""
    weak, medium, strong, over = (results[n] for n in RESPONSES)
    failures: list[str] = []
    for name, r in results.items():
        if r.error:
            failures.append(f"{name}: {r.error}")
    scores = [weak.overall, medium.overall, strong.overall]
    if any(s is None for s in scores):
        failures.append(f"an overall is missing: weak/medium/strong = {scores}")
    elif not (scores[0] < scores[1] < scores[2]):  # type: ignore[operator]
        failures.append(
            f"separation broken: weak={scores[0]} medium={scores[1]} strong={scores[2]}"
        )
    if not over.constraintViolations:
        failures.append("overpromise has no constraint violation (PostgreSQL migration)")
    if not over.findings:
        failures.append("overpromise has no finding (8-week timeline / scope creep)")
    if strong.constraintViolations:
        failures.append(
            f"strong proposal has {len(strong.constraintViolations)} constraint violation(s)"
        )
    return failures


def row(name: str, r: ScoringResult) -> str:
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
    rfp, docs = load(samples)
    results: dict[str, ScoringResult] = {}
    print(f"samples: {samples}")
    for name in RESPONSES:
        results[name] = await score_proposal(rfp, docs[name])
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{Path(name).stem}.json").write_text(results[name].model_dump_json(indent=2))
        print(row(name, results[name]))
        for w in results[name].warnings:
            print(f"warn  {name}: {w}")
    over = results[RESPONSES[3]]
    if not any(c.status == "CONTRADICTED" for c in over.coverage):
        print("note  overpromise has no CONTRADICTED coverage item (violation caught it instead)")

    failures = check(results)
    print()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1
    print(f"OK    4 results written to {CACHE}/")
    return 0


if __name__ == "__main__":
    from app.logs import configure

    configure()
    samples = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLES
    sys.exit(asyncio.run(main(samples)))
