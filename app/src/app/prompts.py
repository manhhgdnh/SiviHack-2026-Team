"""The two self-contained prompts (BACKEND.md §14 — canonical wording, tune here)."""

import json

from app.schema import Requirement

CRITERIA_BLOCK = """- problem_understanding: reflects the client's actual stated problem, not a generic pitch.
- scope_clarity: deliverables specific and unambiguous; clear what's in/out.
- pricing_clarity: pricing stated, broken down, concrete (vs "on request"/deferred).
- timeline_clarity: concrete milestones/dates (vs "in a timely manner").
- completeness: addresses every requirement the RFP asked for.
- tone_persuasiveness: confident, client-focused, professional, not boilerplate.
- risk_transparency: assumptions/dependencies/risks flagged, not hidden."""


def build_extract_prompt(rfp: str) -> str:
    return f"""You extract client requirements from a Request for Proposal (RFP).

Return ONLY valid JSON, no prose, matching:
{{"requirements":[{{"id":"r1","label":"short name","rfpQuote":"verbatim text from the RFP","section":"section header or null"}}]}}

Rules:
- Extract EVERY explicit requirement: the numbered/bulleted asks, AND budget, AND timeline/deadline, AND any hard constraint or exclusion (e.g. "no migration to a new database").
- rfpQuote MUST be copied word-for-word from the RFP. Never paraphrase, summarize, or fix typos.
- Do NOT invent requirements that are not stated in the text.
- ids are sequential: r1, r2, r3...
- label is your own 2-6 word name for the requirement.

RFP:
<<<
{rfp}
>>>"""


def build_score_prompt(requirements: list[Requirement], proposal: str) -> str:
    reqs_json = json.dumps(
        [r.model_dump(include={"id", "label", "rfpQuote"}) for r in requirements],
        ensure_ascii=False,
        indent=1,
    )
    return f"""You are a senior proposal reviewer. You judge a PROPOSAL against a client's REQUIREMENTS. Be specific and grounded; never say "improve clarity" without naming the exact gap.

Return ONLY valid JSON, no prose, matching this shape:
{{
 "coverage":[{{"requirementId":"r1","status":"ADDRESSED|PARTIAL|MISSING|CONTRADICTED","proposalQuote":"verbatim from proposal or null","explanation":"why this status","fix":"one concrete action"}}],
 "scores":[{{"id":"<criterion id>","label":"<criterion name>","score":1-5,"rationale":"specific reason","evidenceQuote":"verbatim from proposal or null","source":"proposal|rfp|null"}}],
 "risks":[{{"type":"OVERCOMMIT|SCOPE_CREEP|UNREALISTIC_TIMELINE|PRICING_MISMATCH|CONTRADICTION","proposalQuote":"verbatim","rfpQuote":"verbatim or null","explanation":"why risky","severity":"HIGH|MEDIUM|LOW"}}]
}}

Coverage status meaning:
- ADDRESSED: proposal clearly satisfies the requirement.
- PARTIAL: mentioned but vague or incomplete.
- MISSING: requirement not addressed anywhere.
- CONTRADICTED: proposal states something that VIOLATES the requirement. Example: requirement says "no migration to a new database", proposal says it will migrate to another platform. This is the most important status — do not mark such a case ADDRESSED just because the topic is mentioned.

The 7 criteria (score each 1-5, id must match exactly):
{CRITERIA_BLOCK}

Rules:
- Every quote (proposalQuote, evidenceQuote, rfpQuote) MUST be copied VERBATIM from the source. Never paraphrase.
- Emit exactly one score object per criterion, all 7, ids spelled exactly as above.
- If a requirement is MISSING, proposalQuote = null.
- fix must be concrete and actionable (name the section and what to add/change).
- risks: flag overpromising, scope creep beyond the ask, timelines/prices implausible for the scope, or direct contradictions of a requirement. Empty list if none.

REQUIREMENTS:
{reqs_json}

PROPOSAL:
<<<
{proposal}
>>>"""
