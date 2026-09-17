"""All prompts — canonical wording, tune here. Bump PROMPT_VERSION when you do: it is part of
every cache key, so stale answers are never served for a new prompt.

Every prompt receives the document *with section markers* (`[§4 Pricing]`) so the model can
name locations by id, and spells out the field order because the model reasons in the order
it writes: coverage → constraint violations → findings → scores.

Scoring runs either as one merged call (local model) or split into
    2a  coverage + constraint violations              (triage; small output)
    2b  three parallel groups of criteria + findings  (see GROUPS)
Completeness is never asked of the model: code computes it from coverage.
"""

import json
from dataclasses import dataclass

from app.schema import (
    LLM_CRITERIA,
    ConstraintViolation,
    CoverageItem,
    RfpExtraction,
)
from app.splitter import Document

PROMPT_VERSION = "3"

RUBRIC: dict[str, str] = {
    "problem_understanding": """problem_understanding — Problem Understanding
  1: generic pitch; the client's situation is not reflected.
  3: restates the client's problem correctly but only at surface level.
  5: reflects the client's specific situation, goals and constraints, in the client's own terms.""",
    "scope_clarity": """scope_clarity — Scope & Deliverables Clarity
  1: generic feature list; unclear what is actually delivered.
  3: deliverables named, but in/out boundaries are fuzzy.
  5: each deliverable specific, with what is and is not included.""",
    "pricing_clarity": """pricing_clarity — Pricing Clarity
  1: no figure, or deferred ("on request", "after discussion").
  3: a total or a range, no breakdown.
  5: itemised breakdown with a total, what is included, positioned against the client's budget.""",
    "timeline_clarity": """timeline_clarity — Timeline Clarity
  1: no dates or durations ("in a timely manner", "ASAP").
  3: phases named or one overall duration, no milestones.
  5: dated milestones mapped to the client's deadlines.""",
    "tone_persuasiveness": """tone_persuasiveness — Tone & Persuasiveness
  1: boilerplate, vendor-centric, could be sent to any client.
  3: professional but generic.
  5: confident, client-focused, evidence-backed, clearly written for this client.""",
    "risk_transparency": """risk_transparency — Risk/Assumptions Transparency
  1: nothing disclosed, or promises that ignore obvious risks.
  3: a few assumptions listed, no dependencies or mitigations.
  5: assumptions, dependencies and risks named with impact and mitigation.""",
}

FINDING_TYPES: dict[str, str] = {
    "OVERCOMMIT": "promises beyond what is credible for the scope, price or team",
    "SCOPE_CREEP": "adds scope the client did not ask for",
    "UNREALISTIC_TIMELINE": "a duration or date implausible for the scope",
    "PRICING_MISMATCH": "a price implausible for the scope",
    "VAGUENESS": "deferred or non-committal wording where a commitment was needed",
    "INCONSISTENCY": "the proposal contradicts itself",
}

# Consistency rules that tie a group's scores to the coverage / violation verdicts it sees.
SCORE_RULES: dict[str, str] = {
    "problem_understanding": "any constraint violation → problem_understanding ≤ 3",
    "pricing_clarity": "a pricing section with 0 money amounts → pricing_clarity ≤ 2",
    "timeline_clarity": "a timeline section with 0 dates or durations → timeline_clarity ≤ 2",
    "risk_transparency": "a constraint violation the proposal does not acknowledge as a risk → risk_transparency ≤ 2",
}


@dataclass(frozen=True)
class Group:
    id: str
    criteria: tuple[str, ...]
    finding_types: tuple[str, ...]  # the finding types this group owns (limits overlap)
    needs_rfp_text: bool  # gets the full RFP, not just requirements / constraints
    needs_signals: bool  # gets the regex evidence block


GROUPS: tuple[Group, ...] = (
    Group(
        "understanding",
        ("problem_understanding", "tone_persuasiveness"),
        ("INCONSISTENCY",),
        needs_rfp_text=True,
        needs_signals=False,
    ),
    Group(
        "commercials",
        ("scope_clarity", "pricing_clarity", "timeline_clarity"),
        ("SCOPE_CREEP", "PRICING_MISMATCH", "UNREALISTIC_TIMELINE", "VAGUENESS"),
        needs_rfp_text=False,
        needs_signals=True,
    ),
    Group(
        "risk",
        ("risk_transparency",),
        ("OVERCOMMIT",),
        needs_rfp_text=False,
        needs_signals=False,
    ),
)

QUOTE_RULES = """\
- Every quote MUST be copied VERBATIM from the source text: at most 20 words, never paraphrased, never stitched from two places.
- Every section id must be one of the [§…] markers in the text.
- Every free-text field is ONE sentence. No preamble, no repetition of the quote."""

MARKERS_NOTE = (
    "The proposal below is split into sections. Each section starts with a marker like "
    '[§4 Pricing]; use that id (e.g. "§4") in every proposalSection, location and '
    "citations[].section field."
)


# ---- helpers -------------------------------------------------------------------------------


def _dump(items: list) -> str:
    return json.dumps(items, ensure_ascii=False, indent=1) if items else "[]"


def _rfp_block(ext: RfpExtraction) -> str:
    if not (ext.requirements or ext.constraints):
        return "REQUIREMENTS: none — NO RFP WAS PROVIDED.\nCONSTRAINTS: none."
    reqs = _dump([r.model_dump(include={"id", "label", "rfpQuote"}) for r in ext.requirements])
    cons = _dump(
        [c.model_dump(include={"id", "kind", "label", "rfpQuote"}) for c in ext.constraints]
    )
    return f"""REQUIREMENTS (from the client's RFP):
{reqs}

CONSTRAINTS (hard limits from the RFP — check each one explicitly):
{cons}"""


def coverage_summary(coverage: list[CoverageItem], violations: list[ConstraintViolation]) -> str:
    """Compact verdicts for the group prompts: one line per item, no quotes."""
    lines = [
        f"- {c.requirementId} {c.status}"
        + (f" in {c.proposalSection}" if c.proposalSection else "")
        + (f": {c.explanation}" if c.explanation else "")
        for c in coverage
    ] or ["- (no requirements to cover)"]
    lines += [
        f"- VIOLATION {v.constraintId} {v.severity}"
        + (f" in {v.proposalSection}" if v.proposalSection else "")
        + f": {v.violation}"
        for v in violations
    ] or ["- no constraint violations"]
    return "\n".join(lines)


def _rubric(criteria: tuple[str, ...] | list[str]) -> str:
    return "\n".join(RUBRIC[c] for c in criteria)


def _finding_types(types: tuple[str, ...] | list[str]) -> str:
    return "; ".join(f"{t} ({FINDING_TYPES[t]})" for t in types)


def _rules(criteria: tuple[str, ...] | list[str]) -> str:
    rules = [SCORE_RULES[c] for c in criteria if c in SCORE_RULES]
    return (" Consistency rules: " + "; ".join(rules) + ".") if rules else ""


COVERAGE_STATUSES = """\
   - ADDRESSED: clearly satisfied. proposalSection = where; proposalQuote, explanation, fix = null.
   - PARTIAL: mentioned but vague or incomplete. proposalQuote = the vague words (≤ 20 words); explanation ≤ 15 words; fix = one sentence.
   - MISSING: not addressed anywhere. proposalSection and proposalQuote = null; explanation ≤ 15 words; fix = one sentence naming the section to add.
   - CONTRADICTED: the proposal states something that violates the requirement. proposalQuote = the offending words; fix = one sentence."""

VIOLATIONS_SPEC = """\
constraintViolations[]: one item for every CONSTRAINT the proposal crosses — total above the budget ceiling, delivery later than the deadline, a technology the client excluded, migrating or replacing what the client said to keep, doing what the client explicitly excluded. proposalQuote = the offending words (≤ 20 words). violation = which limit is crossed and by how much, one sentence. severity = HIGH if it would disqualify the proposal. Empty list only if you checked every constraint and none is crossed. This is the most serious class of error and it is NOT the same as whether the proposal discloses its own risks."""


# ---- call 1 --------------------------------------------------------------------------------


def build_extract_prompt(rfp: Document) -> str:
    return f"""You extract what a client asks for from a Request for Proposal (RFP), so a proposal can be checked against it.

The RFP below is split into sections. Each section starts with a marker like [§2 Requirements]; use that id (e.g. "§2") in every `section` field.

Return ONLY valid JSON matching the schema, no prose. Fill the fields IN THIS ORDER:

1. requirements[]: EVERY explicit thing the proposal must address or deliver — numbered/bulleted asks, deliverables, plans, documentation, support terms — AND the budget AND the timeline/deadline (the proposal must state those too). One item per ask; do not merge two asks into one.
2. constraints[]: hard limits the proposal must NOT cross. kind = BUDGET (a ceiling or range), DEADLINE (a date or duration), TECHNOLOGY (must keep / must not replace / must not use), SCOPE (an explicit exclusion), LEGAL, OTHER. A single RFP sentence may yield both a requirement and a constraint: "integrate with our existing PostgreSQL — no migration" is requirement "integrate with PostgreSQL" AND constraint TECHNOLOGY "no migration to a new database". List every constraint separately; they are checked one by one.
3. suggestedWeights[]: one entry per criterion ({", ".join(LLM_CRITERIA + ["completeness"])}), weight between 0.5 and 3 (1 = neutral) reflecting what THIS client stresses, each with a one-sentence reason that points at the RFP text.

Rules:
- rfpQuote MUST be copied word-for-word from the RFP text, at most 20 words. Never paraphrase, summarize, fix typos, or stitch sentences together.
- section is the marker id of the section the quote is in.
- ids are sequential: r1, r2, r3… and c1, c2, c3…
- label is your own 2–6 word name.
- Do NOT invent requirements or constraints that are not stated in the text.

RFP:
<<<
{rfp.render()}
>>>"""


# ---- call 2a (split): coverage + violations --------------------------------------------------


def build_coverage_prompt(ext: RfpExtraction, proposal: Document) -> str:
    return f"""You check a draft PROPOSAL against the client's REQUIREMENTS and CONSTRAINTS. This is a triage pass: verdicts, locations and fixes — no essays.

{MARKERS_NOTE}

Return ONLY valid JSON matching the schema, no prose. Work IN THIS ORDER:

1. coverage[]: exactly one item per requirement id in REQUIREMENTS (no extras, none skipped).
{COVERAGE_STATUSES}
2. {VIOLATIONS_SPEC}

Rules:
{QUOTE_RULES}

{_rfp_block(ext)}

PROPOSAL:
<<<
{proposal.render()}
>>>"""


# ---- call 2b (split): one group of criteria + its findings -----------------------------------


def build_group_prompt(
    group: Group,
    ext: RfpExtraction,
    proposal: Document,
    coverage: list[CoverageItem],
    violations: list[ConstraintViolation],
    signals_text: str | None = None,
    rfp: Document | None = None,
) -> str:
    n = len(group.criteria)
    ids = ", ".join(group.criteria)
    no_gap_fixes = (
        "\n   Do not write fixes for missing or partial requirements; the coverage verdicts below already carry them."
        if group.id == "risk"
        else ""
    )
    evidence = (
        f"""

PRE-COMPUTED EVIDENCE (extracted from the proposal text by code — treat as facts):
{signals_text}"""
        if group.needs_signals and signals_text
        else ""
    )
    rfp_text = (
        f"""

RFP (the client's own words, for judging understanding and tone):
<<<
{rfp.render()}
>>>"""
        if group.needs_rfp_text and rfp is not None and rfp.sections
        else ""
    )
    return f"""You score a draft PROPOSAL on {n} review criteri{"on" if n == 1 else "a"}. Group id: {group.id}. Other reviewers handle the other criteria; stay within yours.

{MARKERS_NOTE}

Return ONLY valid JSON matching the schema, no prose. Work IN THIS ORDER:

1. findings[]: issues of these types only — {_finding_types(group.finding_types)}. Each with type, severity (HIGH / MEDIUM / LOW), location (section id), proposalQuote (verbatim, ≤ 20 words), explanation (one sentence: why it matters to this client), fix (one sentence that removes it). Empty list if none. Do not repeat a constraint violation listed below as a finding.{no_gap_fixes}
2. scores[]: exactly {n} object{"" if n == 1 else "s"}, ids exactly: {ids}. score 1–5 following the RUBRIC anchors (2 and 4 for in-between). weaknesses = one sentence naming the exact gap (section and words). strengths = one sentence on what genuinely works, or null. citations = 1–3 section pointers {{"source": "proposal" | "rfp", "section": id}} — no sentences. Scores must follow from your findings and from the coverage / violation verdicts below.{_rules(group.criteria)}

RUBRIC (anchors for 1 / 3 / 5):
{_rubric(group.criteria)}

Rules:
{QUOTE_RULES}
- Do NOT compute an overall score; that is done by code.

{_rfp_block(ext)}

COVERAGE VERDICTS AND CONSTRAINT VIOLATIONS (from a previous check — do not redo them):
{coverage_summary(coverage, violations)}{evidence}{rfp_text}

PROPOSAL:
<<<
{proposal.render()}
>>>"""


# ---- merged (local model): everything in one call -------------------------------------------


def build_score_prompt(ext: RfpExtraction, proposal: Document, signals_text: str) -> str:
    has_rfp = bool(ext.requirements or ext.constraints)
    no_rfp_rule = (
        ""
        if has_rfp
        else "\n- NO RFP: coverage = [] and constraintViolations = []. Score the six criteria from the proposal alone."
    )
    return f"""You are a senior proposal reviewer at an IT services company. You judge a draft PROPOSAL against the client's REQUIREMENTS and CONSTRAINTS. Be specific and grounded: name the section, quote the exact words, and never write "improve clarity" without naming the precise gap.

{MARKERS_NOTE}

Return ONLY valid JSON matching the schema, no prose. Work IN THIS ORDER — the fields are in this order on purpose, and every later field must be consistent with the earlier ones:

1. coverage[]: exactly one item per requirement id in REQUIREMENTS (no extras, none skipped).
{COVERAGE_STATUSES}
2. {VIOLATIONS_SPEC}
3. findings[]: issues not already listed as a constraint violation — {_finding_types(list(FINDING_TYPES))}. Each with type, severity, location (section id), proposalQuote (verbatim, ≤ 20 words), explanation (one sentence: why it matters to this client), fix (one sentence that removes it). Empty list if none.
4. scores[]: exactly 6 objects, ids exactly: {", ".join(LLM_CRITERIA)} (completeness is computed by code from your coverage — do not include it). score 1–5 following the RUBRIC anchors (2 and 4 for in-between). weaknesses = one sentence naming the exact gap. strengths = one sentence, or null. citations = 1–3 section pointers {{"source": "proposal" | "rfp", "section": id}} — no sentences. Scores must follow from steps 1–3.{_rules(LLM_CRITERIA)}

RUBRIC (anchors for 1 / 3 / 5):
{_rubric(LLM_CRITERIA)}

PRE-COMPUTED EVIDENCE (extracted from the proposal text by code — treat as facts):
{signals_text}

Rules:
{QUOTE_RULES}
- Do NOT compute an overall score; that is done by code.{no_rfp_rule}

{_rfp_block(ext)}

PROPOSAL:
<<<
{proposal.render()}
>>>"""
