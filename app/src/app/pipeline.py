"""Orchestrator: LLM calls + deterministic glue, emitted as a stream of events.

1. parse        code    sections with hierarchical ids (fallback: paragraphs)  → "sections"
2. LLM call 1           requirements + constraints + suggested weights          → "requirements"
                        cache: hash(prompt version, model, rfp)
3. signals      code    vague phrases, money / dates in pricing & timeline
4. LLM call 2           split (gemini):  2a coverage + violations               → "coverage"
                                         2b three groups in parallel: findings → scores
                        merged (local):  one call, coverage → violations → findings → scores
                        cache: hash(prompt version, model, rfp, proposal[, group])
5. grounding    code    normalise + fuzzy + section check; drop unverified, count them;
                        completeness computed from coverage; findings de-duplicated
6. aggregate    code    overall = Σ(score × weight) / Σ(weight); sort by severity → "scores", "findings", "done"

Weights never reach the LLM and are in no cache key: moving a slider is step 6 only.
Nothing blanks the screen: if 2a fails the "done" event carries call 1's output; if a 2b
group fails, its criteria are null with a note and the other groups still score; a cut
output is salvaged and reported in `warnings`. All of these set `partial: true`.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app import config, usage
from app.aggregate import (
    normalize_weights,
    prioritize_coverage,
    prioritize_findings,
    prioritize_violations,
    weighted_overall,
)
from app.grounding import (
    GroundingStats,
    ground_coverage,
    ground_extraction,
    ground_findings,
    ground_scores,
)
from app.llm import CallStats, LlmProvider, call_json, get_provider
from app.prompts import (
    GROUPS,
    PROMPT_VERSION,
    build_coverage_prompt,
    build_extract_prompt,
    build_group_prompt,
    build_score_prompt,
)
from app.schema import (
    CoverageEvent,
    CoverageLlmOutput,
    CriterionScore,
    EventPayload,
    Finding,
    FindingsEvent,
    GroupLlmOutput,
    Outlines,
    RequirementsEvent,
    RfpExtraction,
    ScoreLlmOutput,
    ScoresEvent,
    ScoringMeta,
    ScoringMode,
    ScoringResult,
    Weights,
)
from app.signals import compute_signals, render_signals
from app.splitter import Document, parse

log = logging.getLogger(__name__)

# Relative to the working directory: /app in the container, app/ when run locally.
CACHE = Path("data/cache")

type Event = tuple[str, EventPayload]


# Providers whose calls are (or replay) Gemini's split-mode prompts.
SPLIT_PROVIDERS = frozenset({"gemini", "replay"})


def split_mode(provider: LlmProvider) -> bool:
    if config.SPLIT_CALLS in ("true", "false"):
        return config.SPLIT_CALLS == "true"
    return provider.name in SPLIT_PROVIDERS


# ---- cache ---------------------------------------------------------------------------------


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


async def cached_call[T: BaseModel](
    kind: str,
    key_parts: tuple[str, ...],
    model_cls: type[T],
    prompt: str,
    provider: LlmProvider,
    reasoning: str | None,
) -> tuple[T, CallStats, bool]:
    """`call_json` behind the disk cache. The *raw* model output is cached (grounding is
    re-applied on every read), together with whether it had to be salvaged, so a cache hit
    reports the same warnings as the original call. Returns (value, stats, cache_hit)."""
    key = _h(kind, PROMPT_VERSION, provider.model, *key_parts)
    cached = _cache_get(key)
    if cached is not None:
        st = cached.get("stats", {})
        stats = CallStats(
            attempts=0, truncated=st.get("truncated", 0), repaired=st.get("repaired", 0)
        )
        return model_cls.model_validate(cached["value"]), stats, True
    usage.check_budget()  # a hit above never reaches here: the cache keeps working at $0
    value, stats = await call_json(provider, prompt, model_cls, reasoning=reasoning)
    usage.record(kind, provider.model, stats.tokens)
    _cache_put(
        key,
        {
            "value": value.model_dump(),
            "stats": {"truncated": stats.truncated, "repaired": stats.repaired},
        },
    )
    return value, stats, False


# ---- the pipeline -------------------------------------------------------------------------


def _reasoning(value: str) -> str | None:
    return value.strip() or None


async def extract_rfp(
    rdoc: Document, provider: LlmProvider
) -> tuple[RfpExtraction, CallStats, bool, GroundingStats]:
    """LLM call 1 plus grounding, behind the cache keyed on the RFP text alone, so
    POST /rfp/extract and a later full run share one LLM call."""
    if not rdoc.sections:  # no RFP: nothing to extract, coverage will be empty
        return RfpExtraction(requirements=[], constraints=[]), CallStats(), False, GroundingStats()
    ext, st, hit = await cached_call(
        "extract",
        (rdoc.text,),
        RfpExtraction,
        build_extract_prompt(rdoc),
        provider,
        _reasoning(config.REASONING_EFFORT_COVERAGE),
    )
    ext, gstats = ground_extraction(ext, rdoc)
    return ext, st, hit, gstats


async def extract_requirements(rfp: str, provider: LlmProvider | None = None) -> RequirementsEvent:
    """POST /rfp/extract: call 1 only. Same cache key as a full run, so a run right after
    costs nothing extra."""
    ext, _, hit, _ = await extract_rfp(parse(rfp), provider or get_provider())
    return RequirementsEvent(
        requirements=ext.requirements,
        constraints=ext.constraints,
        suggestedWeights=ext.suggestedWeights,
        extractCached=hit,
    )


async def run(
    rfp: str,
    proposal: str,
    weights: Weights | None = None,
    provider: LlmProvider | None = None,
) -> AsyncIterator[Event]:
    t0 = time.time()
    provider = provider or get_provider()
    norm_weights = normalize_weights(weights)
    mode: ScoringMode = "split" if split_mode(provider) else "merged"
    calls = CallStats()
    warnings: list[str] = []

    rdoc, pdoc = parse(rfp), parse(proposal)
    sections = Outlines(rfp=rdoc.outline(), proposal=pdoc.outline())
    yield "sections", sections

    # -- call 1 ----------------------------------------------------------------------------
    ext, st, extract_hit, gstats = await extract_rfp(rdoc, provider)
    calls.add(st)
    has_rfp = bool(ext.requirements or ext.constraints)
    yield (
        "requirements",
        RequirementsEvent(
            requirements=ext.requirements,
            constraints=ext.constraints,
            suggestedWeights=ext.suggestedWeights,
            extractCached=extract_hit,
        ),
    )

    signals = compute_signals(pdoc)
    signals_text = render_signals(signals, pdoc)
    doc_key = (rdoc.text, pdoc.text)
    score_cached = True

    def meta() -> ScoringMeta:
        return ScoringMeta(
            model=provider.model,
            temperature=config.TEMPERATURE,
            promptVersion=PROMPT_VERSION,
            mode=mode,
            durationMs=int((time.time() - t0) * 1000),
            llmCalls=calls.attempts,
            truncated=calls.truncated,
            repaired=calls.repaired,
            ungroundedDropped=gstats.dropped,
            fuzzyMatched=gstats.fuzzy,
            extractCached=extract_hit,
            scoreCached=score_cached,
        )

    def result(**overrides: Any) -> ScoringResult:
        base: dict[str, Any] = dict(
            overall=None,
            weights=norm_weights,
            scores=[],
            coverage=[],
            constraintViolations=[],
            findings=[],
            requirements=ext.requirements,
            constraints=ext.constraints,
            suggestedWeights=ext.suggestedWeights,
            signals=signals,
            sections=sections,
            warnings=warnings,
            meta=meta(),
        )
        base.update(overrides)
        return ScoringResult(**base)

    # -- call 2a (or the whole merged call) ---------------------------------------------------
    merged: ScoreLlmOutput | None = None
    try:
        if mode == "merged":
            merged, st, hit = await cached_call(
                "score",
                doc_key,
                ScoreLlmOutput,
                build_score_prompt(ext, pdoc, signals_text),
                provider,
                _reasoning(config.REASONING_EFFORT_COVERAGE),
            )
            calls.add(st)
            score_cached &= hit
            raw_cov, raw_vio = merged.coverage, merged.constraintViolations
        elif has_rfp:
            cov, st, hit = await cached_call(
                "coverage",
                doc_key,
                CoverageLlmOutput,
                build_coverage_prompt(ext, pdoc),
                provider,
                _reasoning(config.REASONING_EFFORT_COVERAGE),
            )
            calls.add(st)
            score_cached &= hit
            raw_cov, raw_vio = cov.coverage, cov.constraintViolations
        else:
            raw_cov, raw_vio = [], []
    except Exception as e:  # the analysis call failed after its retry: ship what we have
        log.exception("coverage/scoring call failed; returning partial result")
        yield "done", result(partial=True, error=f"{type(e).__name__}: {e}")
        return

    coverage, violations = ground_coverage(raw_cov, raw_vio, ext, pdoc, gstats)
    coverage, violations = prioritize_coverage(coverage), prioritize_violations(violations)
    yield "coverage", CoverageEvent(coverage=coverage, constraintViolations=violations)

    # -- call 2b: three groups in parallel (split) --------------------------------------------
    raw_scores: list[CriterionScore] = []
    raw_findings: list[Finding] = []
    failed: dict[str, str] = {}
    if merged is not None:
        raw_scores, raw_findings = merged.scores, merged.findings
    else:
        tasks = [
            cached_call(
                f"group:{g.id}",
                doc_key,
                GroupLlmOutput,
                build_group_prompt(
                    g,
                    ext,
                    pdoc,
                    coverage,
                    violations,
                    signals_text if g.needs_signals else None,
                    rdoc if g.needs_rfp_text else None,
                ),
                provider,
                _reasoning(config.REASONING_EFFORT),
            )
            for g in GROUPS
        ]
        for g, res in zip(
            GROUPS, await asyncio.gather(*tasks, return_exceptions=True), strict=True
        ):
            if isinstance(res, BaseException):
                failed[g.id] = f"{type(res).__name__}: {res}"
                log.error("scoring group %s failed: %s", g.id, failed[g.id])
                continue
            out, st, hit = res
            calls.add(st)
            score_cached &= hit
            raw_scores += out.scores
            raw_findings += out.findings
        for gid, err in failed.items():
            warnings.append(f"scoring group '{gid}' failed: {err}")

    # -- grounding + aggregation ----------------------------------------------------------------
    scores = ground_scores(raw_scores, coverage, ext, rdoc, pdoc, gstats)
    for g in GROUPS:
        if g.id in failed:
            for s in scores:
                if s.id in g.criteria:
                    s.score, s.note = None, f"not assessable: scoring group '{g.id}' failed"
    findings = prioritize_findings(ground_findings(raw_findings, pdoc, gstats))
    if calls.truncated:
        warnings.append(
            f"{calls.truncated} LLM output(s) hit the output limit and were salvaged; "
            "some items may be missing"
        )

    overall = weighted_overall(scores, norm_weights)
    yield "scores", ScoresEvent(scores=scores, overall=overall)
    yield "findings", FindingsEvent(findings=findings)
    yield (
        "done",
        result(
            overall=overall,
            scores=scores,
            coverage=coverage,
            constraintViolations=violations,
            findings=findings,
            partial=bool(failed) or calls.truncated > 0,
        ),
    )


async def score_proposal(
    rfp: str,
    proposal: str,
    weights: Weights | None = None,
    provider: LlmProvider | None = None,
) -> ScoringResult:
    """Blocking form of `run`: the payload of the final "done" event."""
    async for event, payload in run(rfp, proposal, weights, provider):
        if event == "done":
            assert isinstance(payload, ScoringResult)
            return payload
    raise RuntimeError("pipeline ended without a result")
