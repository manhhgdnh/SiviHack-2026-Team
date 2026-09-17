"""Markdown section split — the only regex in the pipeline (BACKEND.md §11)."""

import re
from typing import TypedDict

_HEADER = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_WS = re.compile(r"\s+")


class Section(TypedDict):
    header: str
    level: int
    body: str


def split_sections(md: str) -> list[Section]:
    """Return [{header, level, body}] in order. Text before the first header
    becomes header='preamble', level=0 (skipped if empty)."""
    matches = list(_HEADER.finditer(md))
    out: list[Section] = []
    if not matches or matches[0].start() > 0:
        pre = md[: matches[0].start()] if matches else md
        if pre.strip():
            out.append({"header": "preamble", "level": 0, "body": pre.strip()})
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        out.append(
            {
                "header": m.group(2).strip(),
                "level": len(m.group(1)),
                "body": md[start:end].strip(),
            }
        )
    return out


def section_of(md: str, quote: str | None) -> str | None:
    """Header of the first section that contains `quote` (whitespace/case-insensitive).

    Deterministic section labels for a verbatim quote, so the UI can say *where* a
    requirement lives without trusting the LLM's own `section` guess.
    """
    if not quote:
        return None
    q = _WS.sub(" ", quote).strip().lower()
    if not q:
        return None
    for s in split_sections(md):
        text = _WS.sub(" ", f"{s['header']} {s['body']}").lower()
        if q in text:
            return s["header"]
    return None
