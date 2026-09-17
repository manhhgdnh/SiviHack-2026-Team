"""Quote verification — the anti-hallucination core.

Every quote the LLM emits is checked against the real document *and* against the section
it claims to come from:

* ``verified``   — verbatim (after normalisation) inside the claimed section, or verbatim
                   anywhere when no section was claimed. For a section-only citation: the
                   id exists in that document.
* ``fuzzy``      — found, but not where claimed (location corrected by code), or only a
                   near-match (rapidfuzz partial_ratio ≥ 90). Shown, flagged.
* ``unverified`` — not found. Dropped when DROP_UNGROUNDED (default), else kept + flagged.

`grounding` fields are code-owned: the LLM never sees them in its schema. The three
`ground_*` functions are the stages of the scoring pass; `ground_scoring` chains them for
the merged (single-call) shape.
"""

from dataclasses import dataclass
from typing import NamedTuple

from rapidfuzz import fuzz

from app import config
from app.aggregate import completeness_from_coverage, dedupe_findings
from app.normalize import normalize
from app.schema import (
    CRITERIA,
    CRITERION_LABELS,
    Citation,
    ConstraintViolation,
    CoverageItem,
    CriterionScore,
    Finding,
    GroundingStatus,
    RfpExtraction,
    ScoreLlmOutput,
)
from app.splitter import Document, Section

FUZZY_THRESHOLD = 90
FUZZY_MIN_CHARS = 10  # shorter quotes must be verbatim: "€89,000" is not "€98,000"


class Match(NamedTuple):
    status: GroundingStatus
    section: str | None  # id of the section that really contains the quote


@dataclass
class GroundingStats:
    dropped: int = 0
    fuzzy: int = 0

    def add(self, m: Match) -> bool:
        """Record the match; return True if the item should be kept."""
        if m.status == "fuzzy":
            self.fuzzy += 1
        if m.status == "unverified" and config.DROP_UNGROUNDED:
            self.dropped += 1
            return False
        return True


def _best_section(q: str, sections: list[Section]) -> tuple[Section | None, float]:
    best, best_score = None, 0.0
    for s in sections:
        score = fuzz.partial_ratio(q, s.norm)
        if score > best_score:
            best, best_score = s, score
    return best, best_score


def verify(quote: str | None, doc: Document, claimed: str | None = None) -> Match:
    q = normalize(quote)
    if not q:
        return Match("unverified", None)
    claimed_sec = doc.resolve(claimed)
    if claimed_sec is not None and q in claimed_sec.norm:
        return Match("verified", claimed_sec.id)
    actual = doc.locate(q)
    if actual is not None:
        # verbatim, but either nothing was claimed (fine) or the claim was wrong (flag it)
        return Match("verified" if not claimed else "fuzzy", actual.id)
    if q in doc.norm:  # verbatim, but spanning a section boundary
        return Match(
            "verified" if not claimed else "fuzzy", claimed_sec.id if claimed_sec else None
        )
    if len(q) < FUZZY_MIN_CHARS:
        return Match("unverified", None)
    best, score = _best_section(q, doc.sections)
    if best is not None and score >= FUZZY_THRESHOLD:
        return Match("fuzzy", best.id)
    if fuzz.partial_ratio(q, doc.norm) >= FUZZY_THRESHOLD:
        return Match("fuzzy", claimed_sec.id if claimed_sec else None)
    return Match("unverified", None)


def _canonical(doc: Document, label: str | None) -> str | None:
    """The document's own id for a section label, or None if it resolves to nothing."""
    s = doc.resolve(label)
    return s.id if s else None


# ---- call 1 ------------------------------------------------------------------------------


def ground_extraction(ext: RfpExtraction, rfp: Document) -> tuple[RfpExtraction, GroundingStats]:
    """Verify every RFP quote; pin `section` to where the quote really is."""
    stats = GroundingStats()
    for name in ("requirements", "constraints"):
        kept = []
        for item in getattr(ext, name):
            m = verify(item.rfpQuote, rfp, item.section)
            item.grounding = m.status
            item.section = m.section or item.section
            if stats.add(m):
                kept.append(item)
        setattr(ext, name, kept)
    return ext, stats


# ---- call 2: coverage + violations (2a, or the first half of the merged call) -------------


def ground_coverage(
    coverage: list[CoverageItem],
    violations: list[ConstraintViolation],
    ext: RfpExtraction,
    proposal: Document,
    stats: GroundingStats,
) -> tuple[list[CoverageItem], list[ConstraintViolation]]:
    """Drop items that reference unknown ids; verify every quote; canonicalise sections.
    Items without a quote (ADDRESSED, MISSING) have nothing to verify: grounding stays None."""
    req_ids = {r.id for r in ext.requirements}
    con_ids = {c.id for c in ext.constraints}

    kept_cov: list[CoverageItem] = []
    for c in coverage:
        if c.requirementId not in req_ids:
            continue
        if c.status == "MISSING":
            c.proposalSection, c.proposalQuote, c.grounding = None, None, None
            kept_cov.append(c)
            continue
        if not c.proposalQuote:
            c.proposalQuote, c.grounding = None, None
            c.proposalSection = _canonical(proposal, c.proposalSection)
            kept_cov.append(c)
            continue
        m = verify(c.proposalQuote, proposal, c.proposalSection)
        c.grounding = m.status
        c.proposalSection = m.section or _canonical(proposal, c.proposalSection)
        if stats.add(m):
            kept_cov.append(c)

    kept_vio: list[ConstraintViolation] = []
    for v in violations:
        if v.constraintId not in con_ids:
            continue
        m = verify(v.proposalQuote, proposal, v.proposalSection)
        v.grounding = m.status
        v.proposalSection = m.section or _canonical(proposal, v.proposalSection)
        if stats.add(m):
            kept_vio.append(v)
    return kept_cov, kept_vio


# ---- call 2: scores + findings (2b groups, or the second half of the merged call) ---------


def _ground_citations(
    cits: list[Citation], rfp: Document, proposal: Document, stats: GroundingStats
) -> list[Citation]:
    """A citation names a section and quotes the words that justify the score. The quote is
    checked like every other quote (verbatim → verified, relocated or near → fuzzy with the
    section corrected, invented → dropped); a quote-less citation is verified iff the section
    id exists. Duplicates (same source, section and normalised quote) collapse."""
    kept: list[Citation] = []
    for c in cits:
        doc = rfp if c.source == "rfp" else proposal
        if c.quote:
            m = verify(c.quote, doc, c.section)
            sid = m.section or _canonical(doc, c.section)
            if sid is None or not stats.add(m):
                if sid is None:
                    stats.dropped += 1
                continue
            c.section, c.grounding = sid, m.status
        else:
            sid = _canonical(doc, c.section)
            if sid is None:
                stats.dropped += 1
                continue
            c.section, c.grounding = sid, "verified"
        key = (c.source, c.section, normalize(c.quote))
        if all((k.source, k.section, normalize(k.quote)) != key for k in kept):
            kept.append(c)
    return kept


def ground_scores(
    scores: list[CriterionScore],
    coverage: list[CoverageItem],
    ext: RfpExtraction,
    rfp: Document,
    proposal: Document,
    stats: GroundingStats,
) -> list[CriterionScore]:
    """Exactly one score per criterion, in CRITERIA order, labels filled, citations checked
    (section exists; quote verified like any other).
    First occurrence wins; completeness is always the code-computed one."""
    by_id: dict[str, CriterionScore] = {}
    for s in scores:
        by_id.setdefault(s.id, s)
    by_id["completeness"] = completeness_from_coverage(coverage, ext.requirements)
    out: list[CriterionScore] = []
    for cid in CRITERIA:
        s = by_id.get(cid) or CriterionScore(
            id=cid,
            score=None,
            weaknesses="",
            note="not assessable: the model returned no score for this criterion",
        )
        s.label = CRITERION_LABELS[cid]
        if cid != "completeness":
            s.citations = _ground_citations(s.citations, rfp, proposal, stats)
        out.append(s)
    return out


def ground_findings(
    findings: list[Finding], proposal: Document, stats: GroundingStats
) -> list[Finding]:
    """Verify every finding's quote, correct its location, then de-duplicate across groups."""
    kept: list[Finding] = []
    for f in findings:
        m = verify(f.proposalQuote, proposal, f.location)
        f.grounding = m.status
        f.location = m.section or _canonical(proposal, f.location)
        if stats.add(m):
            kept.append(f)
    return dedupe_findings(kept)


def ground_scoring(
    llm: ScoreLlmOutput, ext: RfpExtraction, rfp: Document, proposal: Document
) -> tuple[ScoreLlmOutput, GroundingStats]:
    """All three stages on the merged single-call shape."""
    stats = GroundingStats()
    llm.coverage, llm.constraintViolations = ground_coverage(
        llm.coverage, llm.constraintViolations, ext, proposal, stats
    )
    llm.scores = ground_scores(llm.scores, llm.coverage, ext, rfp, proposal, stats)
    llm.findings = ground_findings(llm.findings, proposal, stats)
    return llm, stats
