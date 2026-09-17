"""Orchestrator: 2 LLM calls + deterministic glue, with the Layer-A cache (BACKEND.md §15).

split markdown by headers          (section labels for grounded quotes)
LLM call 1: extract requirements   (cached by hash(rfp) — RFP unchanged ⇒ same reqs)
LLM call 2: coverage + 7 scores + risks
grounding: every quote must be a verbatim substring of its source
aggregate: weighted overall + prioritised findings
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app import config
from app.aggregate import (
    normalize_weights,
    prioritize_coverage,
    prioritize_risks,
    weighted_overall,
)
from app.grounding import ground_result
from app.llm import LlmProvider, call_json, get_provider
from app.prompts import build_extract_prompt, build_score_prompt
from app.schema import (
    Requirement,
    RfpExtraction,
    ScoreLlmOutput,
    ScoringMeta,
    ScoringResult,
)
from app.splitter import section_of

# Relative to the working directory: /app in the container, app/ when run locally.
CACHE = Path("data/cache")


def _h(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:16]


def _cache_get(key: str) -> dict[str, Any] | None:
    f = CACHE / f"{key}.json"
    if config.USE_CACHE and f.exists():
        return json.loads(f.read_text())
    return None


def _cache_put(key: str, obj: dict[str, Any]) -> None:
    if config.USE_CACHE:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{key}.json").write_text(json.dumps(obj, ensure_ascii=False))


async def extract_requirements(rfp: str, provider: LlmProvider) -> tuple[list[Requirement], bool]:
    """LLM call 1 behind the Layer-A cache. Returns (requirements, cache_hit)."""
    key = _h("extract", rfp)
    cached = _cache_get(key)
    if cached:
        return [Requirement.model_validate(r) for r in cached["requirements"]], True

    ext = await call_json(provider, build_extract_prompt(rfp), RfpExtraction)
    for r in ext.requirements:
        # Prefer the deterministic section label; fall back to the LLM's own guess.
        r.section = section_of(rfp, r.rfpQuote) or r.section
    _cache_put(key, {"requirements": [r.model_dump() for r in ext.requirements]})
    return ext.requirements, False


async def score_proposal(
    rfp: str,
    proposal: str,
    weights: dict[str, float] | None = None,
    provider: LlmProvider | None = None,
) -> ScoringResult:
    t0 = time.time()
    provider = provider or get_provider()
    norm_weights = normalize_weights(weights)

    requirements, cache_hit = await extract_requirements(rfp, provider)

    # LLM call 2: score + coverage + risk
    llm = await call_json(provider, build_score_prompt(requirements, proposal), ScoreLlmOutput)

    # Grounding
    llm, requirements, dropped = ground_result(llm, requirements, rfp, proposal)

    # Aggregate + order
    overall = weighted_overall(llm.scores, norm_weights)
    coverage = prioritize_coverage(llm.coverage, norm_weights)
    risks = prioritize_risks(llm.risks, norm_weights)

    return ScoringResult(
        overall=overall,
        weights=norm_weights,
        scores=llm.scores,
        coverage=coverage,
        risks=risks,
        requirements=requirements,
        meta=ScoringMeta(
            model=provider.model,
            temperature=config.TEMPERATURE,
            durationMs=int((time.time() - t0) * 1000),
            ungroundedDropped=dropped,
            cacheHit=cache_hit,
        ),
    )
