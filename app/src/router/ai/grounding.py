import re
from dataclasses import dataclass

from .errors import ReviewError
from .schemas import Citation, Evidence


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    first_line: int
    last_line: int
    section: str
    quote: str


class Document:
    def __init__(self, text: str, source: str):
        self.text = text
        self.source = source
        self.lines = text.split("\n")
        self.headings: list[str] = []
        current = "Document"
        fence = None
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            marker = re.match(r"^(`{3,}|~{3,})", stripped)
            if marker:
                char = marker.group(1)[0]
                fence = None if fence == char else char if fence is None else fence
            if fence is None and not marker:
                heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
                if heading:
                    current = heading.group(1)
                elif (
                    i + 1 < len(self.lines)
                    and stripped
                    and re.fullmatch(r"\s*(?:={3,}|-{3,})\s*", self.lines[i + 1])
                ):
                    current = stripped
            self.headings.append(current)

    def locate(self, quote: str, section: str | None = None) -> Span:
        if not quote.strip():
            raise ReviewError("ungrounded_evidence", "A source quote is empty.", 502)
        # Permit only whitespace differences. Return actual source text, never the LLM copy.
        pattern = r"\s+".join(re.escape(p) for p in re.split(r"\s+", quote.strip()))
        matches = list(re.finditer(pattern, self.text))
        if len(matches) > 1 and section:
            matches = [
                m for m in matches if self.headings[self.text.count("\n", 0, m.start())] == section
            ]
        if len(matches) != 1:
            raise ReviewError(
                "ungrounded_evidence", "A quote is absent or ambiguous in its source document.", 502
            )
        match = matches[0]
        first = self.text.count("\n", 0, match.start()) + 1
        last = self.text.count("\n", 0, match.end() - 1) + 1
        return Span(
            match.start(), match.end(), first, last, self.headings[first - 1], match.group()
        )

    def ground(self, evidence: Evidence) -> Evidence:
        if evidence.source != self.source:
            raise ReviewError("ungrounded_evidence", "Evidence references the wrong document.", 502)
        span = self.locate(evidence.quote, evidence.section)
        # Section labels and line offsets are always derived from the original input.
        return Evidence(source=self.source, section=span.section, quote=span.quote)

    def citation(self, evidence: Evidence) -> Citation:
        span = self.locate(evidence.quote, evidence.section)
        return Citation(
            witness="R" if self.source == "rfp" else "P",
            section=span.section,
            **{"from": span.first_line, "to": span.last_line},
        )
