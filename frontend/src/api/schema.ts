/**
 * The edition's vocabulary.
 *
 * P is the base text — the draft proposal under review.
 * R is the collating witness — the client's RFP, the authority the draft
 * is measured against. Every judgment the editor makes carries the siglum
 * and line of the passage that produced it.
 */

export type Siglum = "R" | "P"

export interface Citation {
  witness: Siglum
  /** The source's own section label, e.g. "4.4" — what a reader would quote. */
  section: string
  /** 1-indexed, inclusive, into the witness's `lines`. */
  from: number
  to: number
}

export interface Witness {
  siglum: Siglum
  title: string
  subtitle: string
  lines: string[]
}

export type RequirementStatus =
  | "addressed"
  | "partial"
  | "missing"
  | "contradicted"

export interface Requirement {
  id: string
  /** Printed reference in the margin column. Every one is deep-linkable. */
  ref: string
  section: string
  text: string
  status: RequirementStatus
  /** Where in the proposal it is answered, when it is. */
  answeredAt: Citation | null
  source: Citation
  note: string
  severity?: "low" | "medium" | "high" | "critical"
  mandatory?: boolean
  suggestedFix?: string | null
  anchor_id?: string
}

export type Severity = "must" | "should" | "optional"

export interface Issue {
  id: string
  ref: string
  severity: Severity
  criterionId: string
  /** The lemma: the words being judged, or a short name for their absence. */
  lemma: string
  /** Verbatim from the proposal, when there is text to quote. */
  quoted: string | null
  location: Citation
  /** The RFP passage that makes this a problem. */
  against: Citation | null
  whyItMatters: string
  suggestedFix: string
  fixKind?: "action"
}

export interface Criterion {
  id: string
  name: string
  whatToCheck: string
  enabled: boolean
  /** Share of a fixed 100. Enabled weights always total 100. */
  weight: number
  custom?: boolean
}

export interface CriterionScore {
  criterionId: string
  /** 1–5. */
  score: number
  strength: string | null
  weakness: string
  citations: Citation[]
}

export type Verdict = "ready" | "fix" | "not-ready"

export interface Review {
  schema_version?: "1.0"
  readiness?: "ready" | "minor_revision" | "major_revision" | "not_ready"
  readiness_reasons?: string[]
  overall_100?: number
  counters?: Record<string, number>
  top_actions?: string[]
  notifications?: { type: "contradiction"; requirement_id: string; severity: string; message: string; anchor_id: string }[]

  verdict: Verdict
  /** Weighted mean of enabled criteria, 1–5, one decimal. */
  overall: number
  criteria: CriterionScore[]
  requirements: Requirement[]
  issues: Issue[]
}

export interface WeightSuggestion {
  criterionId: string
  weight: number
  reason: string
}

export interface ReviewInput {
  rfp: string
  proposal: string
  criteria: Criterion[]
}
