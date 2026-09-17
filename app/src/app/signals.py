"""Deterministic evidence computed by code before LLM call 2.

Regexes catch what a model scores inconsistently: vague deferrals ("on request", "TBD",
"in due course"), and whether the pricing / timeline sections contain any concrete amounts
or dates at all. The result goes into the scoring prompt as *pre-computed evidence* and
into the API response, so Pricing and Timeline scores rest on countable facts.
"""

import re

from app.schema import Mention, NumericSignal, Signals, VagueHit
from app.splitter import Document, Section

VAGUE_PHRASES: list[str] = [
    "on request",
    "upon request",
    "available on request",
    "tbd",
    "tbc",
    "tba",
    "asap",
    "as soon as possible",
    "in due course",
    "in a timely manner",
    "in a timely fashion",
    "at a later stage",
    "at a later date",
    "to be discussed",
    "to be determined",
    "to be confirmed",
    "to be agreed",
    "to be defined",
    "to be finalized",
    "to be finalised",
    "will be confirmed",
    "will be determined",
    "will be provided",
    "will be communicated",
    "will be discussed",
    "will be agreed",
    "upon further discussion",
    "after further discussion",
    "subject to discussion",
    "after discovery",
    "depending on final scope",
    "depend on final scope",
    "depends on final scope",
    "shortly after",
    "as needed",
    "where appropriate",
    "best effort",
    "competitive rates",
    "market rates",
]
_VAGUE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(p) for p in sorted(VAGUE_PHRASES, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

_CUR = r"(?:€|eur|\$|usd|£|gbp|chf)"
_MONEY = re.compile(
    rf"{_CUR}\s?\d[\d.,]*\s?(?:k|m|million|thousand)?\b|\b\d[\d.,]*\s?(?:k|m)?\s?{_CUR}\b",
    re.IGNORECASE,
)
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = re.compile(
    r"\b(?:"
    r"\d{1,2}\s?(?:-|–)?\s?(?:weeks?|months?|days?|years?)\b"  # 8 weeks, 3-month, 2–3 weeks
    r"|(?:weeks?|months?|days?|phases?|sprints?|milestones?)\s+\d{1,2}(?:\s?(?:-|–)\s?\d{1,2})?\b"  # Weeks 1–10
    r"|q[1-4](?:\s+\d{4})?\b"
    rf"|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"  # March 3, 2026
    rf"|\d{{1,2}}\s+{_MONTHS}(?:\s+\d{{4}})?\b"  # 3 March 2026
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4}"
    r"|end of (?:q[1-4]|(?:the|this|next) (?:quarter|month|year))"
    r")",
    re.IGNORECASE,
)

_PRICING_HEADER = re.compile(
    r"\b(?:pric(?:e|es|ing)|costs?|budget|investment|fees?|commercials?|quot(?:e|ation)|payment)\b",
    re.IGNORECASE,
)
_TIMELINE_HEADER = re.compile(
    r"\b(?:timeline|timing|schedule|milestones?|roadmap|phases|phasing|rollout|roll-out|delivery|duration)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
CONTEXT_CHARS = 100


def _context(body: str, start: int, end: int) -> str:
    lo, hi = max(0, start - CONTEXT_CHARS), min(len(body), end + CONTEXT_CHARS)
    snippet = _WS.sub(" ", body[lo:hi]).strip()
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(body) else "")


def _mentions(pattern: re.Pattern[str], sections: list[Section]) -> list[Mention]:
    out: list[Mention] = []
    for s in sections:
        for m in pattern.finditer(s.body):
            out.append(Mention(value=_WS.sub(" ", m.group(0)).strip(), section=s.id))
    return out


def compute_signals(doc: Document) -> Signals:
    vague: list[VagueHit] = []
    for s in doc.sections:
        for m in _VAGUE.finditer(s.body):
            vague.append(
                VagueHit(
                    phrase=m.group(0).lower(),
                    section=s.id,
                    context=_context(s.body, m.start(), m.end()),
                )
            )
    return Signals(
        vaguePhrases=vague,
        pricing=NumericSignal(
            sections=[s.id for s in doc.sections if _PRICING_HEADER.search(s.header)],
            mentions=_mentions(_MONEY, doc.sections),
        ),
        timeline=NumericSignal(
            sections=[s.id for s in doc.sections if _TIMELINE_HEADER.search(s.header)],
            mentions=_mentions(_DATE, doc.sections),
        ),
    )


def _label(doc: Document, sid: str | None) -> str:
    s = doc.resolve(sid) if sid else None
    return f"{s.id} {s.header}" if s else (sid or "?")


def _numeric_block(name: str, unit: str, sig: NumericSignal, doc: Document) -> list[str]:
    lines = [f"{name} sections: " + (", ".join(_label(doc, s) for s in sig.sections) or "none")]
    inside = [m for m in sig.mentions if m.section in sig.sections]
    outside = [m for m in sig.mentions if m.section not in sig.sections]
    lines.append(
        f"  {unit} inside those sections: {len(inside)}"
        + (" — " + ", ".join(m.value for m in inside) if inside else "")
    )
    if outside:
        by_sec: dict[str, list[str]] = {}
        for m in outside:
            by_sec.setdefault(m.section or "?", []).append(m.value)
        lines.append(
            f"  {unit} elsewhere: "
            + "; ".join(f"{_label(doc, sid)}: {', '.join(vals)}" for sid, vals in by_sec.items())
        )
    return lines


def render_signals(sig: Signals, doc: Document) -> str:
    """Compact plain-text block for the scoring prompt."""
    lines = _numeric_block("Pricing", "money amounts", sig.pricing, doc)
    lines += _numeric_block("Timeline", "dates/durations", sig.timeline, doc)
    if sig.vaguePhrases:
        lines.append(f"Vague / deferring phrases: {len(sig.vaguePhrases)}")
        for v in sig.vaguePhrases[:12]:
            lines.append(f'  - "{v.phrase}" in {_label(doc, v.section)}: {v.context}')
        if len(sig.vaguePhrases) > 12:
            lines.append(f"  … and {len(sig.vaguePhrases) - 12} more")
    else:
        lines.append("Vague / deferring phrases: none")
    return "\n".join(lines)
