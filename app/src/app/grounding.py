"""Verbatim-quote validation — the anti-hallucination core (BACKEND.md §12).

Every quote the LLM emits must be a real substring of its source document. We only set
flags by default; DROP_UNGROUNDED=true removes unverified findings instead.
"""

import re

from app import config
from app.schema import Requirement, ScoreLlmOutput

_WS = re.compile(r"\s+")

try:  # optional fuzzy fallback for quotes the LLM lightly paraphrased
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover - depends on the installed extras
    _fuzz = None


def normalize(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def is_grounded(quote: str | None, source: str) -> bool:
    """True iff quote appears verbatim (whitespace/case-insensitive) in source."""
    if not quote:
        return False
    q, src = normalize(quote), normalize(source)
    if not q:
        return False
    if q in src:
        return True
    if _fuzz is not None:
        return _fuzz.partial_ratio(q, src) >= 90
    return False


def ground_result(
    llm: ScoreLlmOutput,
    requirements: list[Requirement],
    rfp: str,
    proposal: str,
) -> tuple[ScoreLlmOutput, list[Requirement], int]:
    """Set .grounded on every object; optionally drop ungrounded findings.
    Returns (llm, requirements, dropped_count)."""
    dropped = 0
    for r in requirements:
        r.grounded = is_grounded(r.rfpQuote, rfp)

    kept_cov = []
    for c in llm.coverage:
        c.grounded = c.proposalQuote is not None and is_grounded(c.proposalQuote, proposal)
        # MISSING legitimately has no quote — keep it regardless.
        if c.status == "MISSING" or c.grounded or not config.DROP_UNGROUNDED:
            kept_cov.append(c)
        else:
            dropped += 1
    llm.coverage = kept_cov

    for s in llm.scores:
        src = proposal if s.source == "proposal" else rfp if s.source == "rfp" else proposal
        s.grounded = is_grounded(s.evidenceQuote, src) if s.evidenceQuote else False

    kept_risk = []
    for k in llm.risks:
        k.grounded = is_grounded(k.proposalQuote, proposal)
        if k.grounded or not config.DROP_UNGROUNDED:
            kept_risk.append(k)
        else:
            dropped += 1
    llm.risks = kept_risk
    return llm, requirements, dropped
