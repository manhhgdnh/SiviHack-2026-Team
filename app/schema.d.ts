// Loose contract for the frontend. Backend may add fields; frontend should ignore unknowns.
// Copy this next to the frontend's api/ folder, or generate a strict one from
// http://localhost/api/openapi.json — operationIds are stable (score_score, score_stream, meta_health).
//
// Two endpoints, same request body:
//   POST /api/score          → ScoringResult (blocking; 200 even when `partial`)
//   POST /api/score/stream   → text/event-stream, events in this order:
//        sections → requirements → coverage → scores → findings → done   (or `error` at any point)
//        plus ": ping" comment lines every 15 s while an LLM call is in flight.

export type CriterionId =
  | "problem_understanding"
  | "scope_clarity"
  | "pricing_clarity"
  | "timeline_clarity"
  | "completeness"
  | "tone_persuasiveness"
  | "risk_transparency";
export type CoverageStatus = "ADDRESSED" | "PARTIAL" | "MISSING" | "CONTRADICTED";
export type Severity = "HIGH" | "MEDIUM" | "LOW";
export type ConstraintKind = "BUDGET" | "DEADLINE" | "TECHNOLOGY" | "SCOPE" | "LEGAL" | "OTHER";
export type FindingType = string; // OVERCOMMIT | SCOPE_CREEP | UNREALISTIC_TIMELINE | PRICING_MISMATCH | VAGUENESS | INCONSISTENCY
export type Source = "proposal" | "rfp";
/** verified = verbatim in the claimed section (or, for a citation, the section exists);
 *  fuzzy = found but paraphrased or relocated (show + flag); unverified = not found (dropped by
 *  default). null = nothing to verify (ADDRESSED / MISSING coverage carry no quote). */
export type Grounding = "verified" | "fuzzy" | "unverified" | null;

/** Section ids are hierarchical: "§2", "§3.1"; "§0" is the title/front matter; "¶4" a paragraph
 *  when the document has no headings. Every location below is one of these ids, and the
 *  `sections` event / field lists them with their headers. */
export interface SectionRef {
  id: string;
  header: string;
}
export interface DocOutline {
  count: number;
  sections: SectionRef[];
}

/** A pointer to a section of one document. No sentence: the UI has the text. */
export interface Citation {
  source: Source;
  section: string;
  grounding?: Grounding;
}

export interface Requirement {
  id: string; // r1, r2…
  label: string;
  rfpQuote: string; // ≤ 20 words
  section?: string | null;
  grounding?: Grounding;
}

/** A hard limit the proposal must not cross — distinct from a requirement to deliver. */
export interface Constraint {
  id: string; // c1, c2…
  kind: ConstraintKind;
  label: string;
  rfpQuote: string;
  section?: string | null;
  grounding?: Grounding;
}

export interface WeightSuggestion {
  criterionId: CriterionId;
  weight: number; // relative, 1 = neutral
  reason: string;
}

export interface CoverageItem {
  requirementId: string;
  status: CoverageStatus;
  proposalSection: string | null; // where it is addressed; null when MISSING
  proposalQuote: string | null; // ≤ 20 words; only for PARTIAL / CONTRADICTED
  explanation: string | null; // ≤ 15 words; null when ADDRESSED
  fix: string | null; // one sentence; null when ADDRESSED
  grounding?: Grounding;
}

/** The heaviest class of error: the proposal crosses a client constraint. */
export interface ConstraintViolation {
  constraintId: string;
  proposalSection: string | null;
  proposalQuote: string; // ≤ 20 words
  violation: string;
  severity: Severity;
  fix: string;
  grounding?: Grounding;
}

export interface CriterionScore {
  id: CriterionId;
  label: string;
  score: number | null; // 1..5; null = not assessable (see `note`)
  strengths?: string | null; // one sentence
  weaknesses: string; // one sentence
  citations: Citation[]; // section pointers
  /** "computed from coverage: …" on completeness; "not assessable: …" when null. */
  note?: string | null;
}

export interface Finding {
  type: FindingType;
  severity: Severity;
  location?: string | null; // proposal section id
  proposalQuote: string; // ≤ 20 words
  explanation: string;
  fix: string;
  grounding?: Grounding;
}

/** Deterministic evidence computed by code from the proposal (also fed to the model). */
export interface Signals {
  vaguePhrases: { phrase: string; section: string | null; context: string }[];
  pricing: { sections: string[]; mentions: { value: string; section: string | null }[] };
  timeline: { sections: string[]; mentions: { value: string; section: string | null }[] };
}

export interface ScoringResult {
  overall: number | null; // Σ(score×weight)/Σ(weight) over scored criteria; null if nothing scored
  weights: Record<string, number>;
  scores: CriterionScore[]; // always 7, in CriterionId order; completeness is code-computed
  coverage: CoverageItem[]; // sorted CONTRADICTED → MISSING → PARTIAL → ADDRESSED
  constraintViolations: ConstraintViolation[]; // sorted by severity
  findings: Finding[]; // sorted by severity, de-duplicated
  requirements: Requirement[];
  constraints: Constraint[];
  suggestedWeights: WeightSuggestion[];
  signals: Signals;
  sections: { rfp: DocOutline; proposal: DocOutline };
  /** Something is missing. `error` = a call failed outright (only requirements are real);
   *  `warnings` = a scoring group failed (its criteria are null) or a cut output was salvaged. */
  partial: boolean;
  error?: string | null;
  warnings?: string[];
  meta?: {
    model?: string;
    temperature?: number;
    promptVersion?: string;
    mode?: "split" | "merged"; // split = 2a + 3 parallel groups (gemini); merged = one call (local)
    durationMs?: number;
    llmCalls?: number; // calls actually made (cache hits excluded)
    truncated?: number; // outputs cut at the token budget
    repaired?: number; // outputs that needed json_repair
    ungroundedDropped?: number;
    fuzzyMatched?: number;
    extractCached?: boolean;
    scoreCached?: boolean;
  };
}

export interface ScoreRequest {
  rfp?: string; // optional: without it coverage is empty and completeness is null
  proposal: string;
  weights?: Record<string, number>; // e.g. { pricing_clarity: 2 }; never sent to the LLM
}

// ---- SSE event payloads (POST /score/stream) ----
export interface SectionsEvent {
  rfp: DocOutline;
  proposal: DocOutline;
}
export interface RequirementsEvent {
  requirements: Requirement[];
  constraints: Constraint[];
  suggestedWeights: WeightSuggestion[];
  extractCached: boolean;
}
export interface CoverageEvent {
  coverage: CoverageItem[];
  constraintViolations: ConstraintViolation[];
}
export interface ScoresEvent {
  scores: CriterionScore[];
  overall: number | null;
}
export interface FindingsEvent {
  findings: Finding[];
}
export interface ErrorEvent {
  stage: string; // last event that was emitted before the failure
  error: string;
}
export type StreamEvent =
  | { event: "sections"; data: SectionsEvent }
  | { event: "requirements"; data: RequirementsEvent }
  | { event: "coverage"; data: CoverageEvent }
  | { event: "scores"; data: ScoresEvent }
  | { event: "findings"; data: FindingsEvent }
  | { event: "done"; data: ScoringResult }
  | { event: "error"; data: ErrorEvent };
