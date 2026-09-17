"""One normaliser for every text comparison in the pipeline.

Markdown emphasis, curly quotes, typographic dashes, list markers, non-breaking spaces and
line wrapping all make a faithful quote miss a plain substring test. Both sides of every
comparison go through `normalize`, so the only thing left to differ is the words.
"""

import re

_TRANSLATE = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‹": "'",
        "›": "'",
        "–": "-",
        "—": "-",
        "‑": "-",
        "−": "-",
        "…": "...",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)
# list / quote markers at the start of a line: "- ", "* ", "• ", "1. ", "2) ", "> "
_LINE_MARKERS = re.compile(r"^[ \t]*(?:[-*+•>]|\d{1,3}[.)])[ \t]+", re.MULTILINE)
# emphasis, code, heading and table markers
_MD = re.compile(r"[*_`#|~]+")
_WS = re.compile(r"\s+")


def normalize(s: str | None) -> str:
    if not s:
        return ""
    s = s.translate(_TRANSLATE)
    s = _LINE_MARKERS.sub("", s)
    s = _MD.sub("", s)
    return _WS.sub(" ", s).strip().lower()
