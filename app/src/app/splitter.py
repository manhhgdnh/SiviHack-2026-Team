"""Section parsing with hierarchical ids — the location system for every citation.

Every heading level is a section boundary; ids follow the heading tree (`§3`, `§3.2`). A
single top-level heading is the document title and becomes `§0` together with any
front matter, so numbering starts at the first real section. Documents with no markdown
headings (PDF exports, bold-line "headings", ALL-CAPS labels) fall back to pseudo-headings,
and plain prose falls back to paragraphs (`¶1`, `¶2`, …), so a quote always has a location.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.normalize import normalize
from app.schema import DocOutline, SectionRef

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
# a whole line in bold: **Pricing**  /  __Team__:
_BOLD_LINE = re.compile(r"^[ \t]*(?:\*\*|__)(.+?)(?:\*\*|__)[ \t]*:?[ \t]*$", re.MULTILINE)
# a short ALL-CAPS line, optionally numbered: "3. TIMELINE AND MILESTONES"
_CAPS_LINE = re.compile(
    r"^[ \t]*(?:\d+(?:\.\d+)*[.)]?[ \t]+)?([A-Z][A-Z0-9 &/,'\-]{3,60})[ \t]*:?[ \t]*$",
    re.MULTILINE,
)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_LABEL_NOISE = re.compile(r"^(?:#+\s*|section\s+|sec\.?\s+)|[\s:.\-–—]+$", re.IGNORECASE)

type Mode = Literal["headings", "pseudo", "paragraphs", "empty"]


@dataclass
class Section:
    id: str
    header: str
    level: int
    body: str
    norm: str = field(default="", repr=False)  # normalize(header + body), for matching

    def __post_init__(self) -> None:
        if not self.norm:
            self.norm = normalize(f"{self.header}\n{self.body}")

    def ref(self) -> SectionRef:
        return SectionRef(id=self.id, header=self.header)


@dataclass
class Document:
    text: str
    sections: list[Section]
    mode: Mode
    norm: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.norm:
            self.norm = normalize(self.text)

    # -- lookup ---------------------------------------------------------------------------

    def resolve(self, label: str | None) -> Section | None:
        """Section for a label the LLM wrote: an id ("§4", "4", "¶2"), a header, or
        "§4 Pricing" / "Section 4" / "## Pricing" / "PRICING:"."""
        if not label:
            return None
        raw = _LABEL_NOISE.sub("", label.strip()).strip()
        if not raw:
            return None
        key = normalize(raw)
        bare = key.lstrip("§¶").strip()
        for s in self.sections:
            sid = s.id.lstrip("§¶")
            if key in (s.id.lower(), sid) or bare == sid:
                return s
        by_header = {normalize(s.header): s for s in self.sections}
        if key in by_header:
            return by_header[key]
        for s in self.sections:
            if key == normalize(f"{s.id} {s.header}") or bare == normalize(
                f"{s.id.lstrip('§¶')} {s.header}"
            ):
                return s
        if len(key) >= 4:
            for s in self.sections:
                h = normalize(s.header)
                if len(h) >= 4 and (key in h or h in key):
                    return s
        return None

    def locate(self, quote: str | None) -> Section | None:
        """First section whose text contains the (normalised) quote."""
        q = normalize(quote)
        if not q:
            return None
        for s in self.sections:
            if q in s.norm:
                return s
        return None

    # -- presentation ---------------------------------------------------------------------

    def outline(self) -> DocOutline:
        return DocOutline(count=len(self.sections), sections=[s.ref() for s in self.sections])

    def render(self) -> str:
        """The document with a `[§id Header]` marker before each section, for prompts."""
        parts = [f"[{s.id} {s.header}]\n{s.body}".rstrip() for s in self.sections]
        return "\n\n".join(parts)


# -- parsing ------------------------------------------------------------------------------


def _slice(md: str, marks: list[tuple[int, int, int, str]]) -> list[tuple[int, str, str]]:
    """marks = (start, end_of_heading_line, level, title) → [(level, title, body)]."""
    out: list[tuple[int, str, str]] = []
    for i, (_, body_start, level, title) in enumerate(marks):
        body_end = marks[i + 1][0] if i + 1 < len(marks) else len(md)
        out.append((level, title, md[body_start:body_end].strip()))
    return out


def _number(md: str, marks: list[tuple[int, int, int, str]]) -> list[Section]:
    preamble = md[: marks[0][0]].strip()
    parts = _slice(md, marks)
    root = min(level for level, _, _ in parts)
    title_mode = parts[0][0] == root and sum(1 for level, _, _ in parts if level == root) == 1

    sections: list[Section] = []
    if title_mode:
        level, title, body = parts.pop(0)
        head = "\n\n".join(p for p in (preamble, body) if p)
        sections.append(Section("§0", title, level, head))
    elif preamble:
        sections.append(Section("§0", "preamble", 0, preamble))

    counters: dict[int, int] = {}
    for level, title, body in parts:
        counters[level] = counters.get(level, 0) + 1
        for deeper in [lv for lv in counters if lv > level]:
            del counters[deeper]
        sid = "§" + ".".join(str(counters[lv]) for lv in sorted(counters))
        sections.append(Section(sid, title, level, body))
    return sections


def _heading_marks(md: str) -> list[tuple[int, int, int, str]]:
    return [
        (m.start(), m.end(), len(m.group(1)), m.group(2).strip()) for m in _HEADING.finditer(md)
    ]


def _pseudo_marks(md: str) -> list[tuple[int, int, int, str]]:
    marks = [(m.start(), m.end(), 1, m.group(1).strip()) for m in _BOLD_LINE.finditer(md)]
    for m in _CAPS_LINE.finditer(md):
        title = m.group(1).strip()
        if sum(ch.isalpha() for ch in title) >= 3:
            marks.append((m.start(), m.end(), 1, title))
    return sorted(marks)


def _paragraphs(md: str) -> list[Section]:
    out: list[Section] = []
    for chunk in _PARAGRAPH_BREAK.split(md):
        body = chunk.strip()
        if not body:
            continue
        first = body.splitlines()[0].strip()
        header = first if len(first) <= 48 else first[:47].rstrip() + "…"
        out.append(Section(f"¶{len(out) + 1}", header, 0, body))
    return out


def parse(md: str) -> Document:
    if not md or not md.strip():
        return Document(md or "", [], "empty")
    marks = _heading_marks(md)
    if marks:
        return Document(md, _number(md, marks), "headings")
    marks = _pseudo_marks(md)
    if marks:
        return Document(md, _number(md, marks), "pseudo")
    return Document(md, _paragraphs(md), "paragraphs")
