/**
 * The edition's vocabulary.
 *
 * P is the base text — the draft proposal under review.
 * R is the collating witness — the client's RFP, the authority the draft
 * is measured against. Every judgment the editor makes carries the siglum
 * and section of the passage that produced it.
 *
 * The wire shapes live in `./generated` (from `app/openapi.json`); `adapt.ts`
 * turns them into these.
 */

import type {
  ConstraintKind,
  CriterionId,
  FindingType,
  Outlines,
  ScoringMeta,
  Signals,
} from "@/api/generated/types.gen"

export type {
  ConstraintKind,
  CriterionId,
  FindingType,
  Outlines,
  ScoringMeta,
  SectionRef,
  Signals,
} from "@/api/generated/types.gen"

export type Siglum = "R" | "P"

/** UI weights: shares of 100 keyed by criterion; a disabled criterion is sent as 0. */
export type Weights = Record<CriterionId, number>

export interface Citation {
  witness: Siglum
  /** Backend section id: "§3.1", "§0" (title / front matter), "¶4"; "" when unknown. */
  sectionId: string
  /** That section's header from the outline; "" when the id is unknown. */
  header: string
  /** Printed form without the siglum: "§3.1 · Pricing" (the Siglum component adds R/P). */
  label: string
  /**
   * Verbatim words to mark in the witness; null for a section-only pointer
   * (an addressed requirement, a code-built completeness citation).
   */
  quote: string | null
  /** The backend found the words only fuzzily, or in another section than claimed. */
  fuzzy: boolean
}

export interface Witness {
  siglum: Siglum
  title: string
  subtitle: string
  /** The document as written — Markdown, set as a page. */
  text: string
}

export type RequirementStatus = "addressed" | "partial" | "missing" | "contradicted"

export interface Requirement {
  id: string
  /** The model's 2–6 word name for the ask. */
  label: string
  /** The RFP header the ask sits under; "RFP" when unknown. */
  section: string
  /** The RFP's own words, markdown stripped. */
  text: string
  /** "missing" when the model gave no verdict at all. */
  status: RequirementStatus
  /** Where in the proposal it is answered, when it is; quote null when addressed. */
  answeredAt: Citation | null
  source: Citation
  /** The coverage explanation; "" for an addressed requirement. */
  note: string
}

export type Severity = "must" | "should" | "optional"
export type IssueKind = "coverage" | "finding" | "violation"

interface IssueBase {
  id: string
  severity: Severity
  criterionId: CriterionId
  /** The lemma: the words being judged, or a short name for their absence. */
  lemma: string
  /** Verbatim from the proposal, when there is text to quote. */
  quoted: string | null
  /** Where in the proposal the problem is; null when the draft says nothing at all. */
  location: Citation | null
  /** The RFP passage that makes this a problem. */
  against: Citation | null
  whyItMatters: string
  /** Null only on a coverage entry the model left without a fix. */
  suggestedFix: string | null
}

export type Issue = IssueBase &
  (
    | { kind: "coverage"; status: Exclude<RequirementStatus, "addressed">; requirementId: string }
    | { kind: "finding"; findingType: FindingType }
    | {
        kind: "violation"
        constraintId: string
        constraintKind: ConstraintKind
        /** The backend's own grading; the UI files every violation under must fix. */
        graded: Severity
      }
  )

export interface Constraint {
  id: string
  kind: ConstraintKind
  label: string
  source: Citation
}

export interface Criterion {
  id: CriterionId
  name: string
  whatToCheck: string
  enabled: boolean
  /** Share of a fixed 100. Enabled weights always total 100. */
  weight: number
}

export interface CriterionScore {
  criterionId: CriterionId
  /** 1–5, or null when not assessable (see `note`). */
  score: number | null
  strength: string | null
  weakness: string
  note: string | null
  citations: Citation[]
}

export type Verdict = "ready" | "fix" | "not-ready"

export interface WeightSuggestion {
  criterionId: CriterionId
  /** Share of 100 (the backend's relative weight, normalised). */
  weight: number
  reason: string
}

/** What "Suggest weights from the RFP" brings back: the suggestions and what was read. */
export interface WeightAdvice {
  suggestions: WeightSuggestion[]
  requirements: number
  constraints: number
}

export interface Review {
  /** The backend's weighted mean with the weights that were sent; null when nothing scored. */
  overall: number | null
  verdict: Verdict | null
  criteria: CriterionScore[]
  requirements: Requirement[]
  constraints: Constraint[]
  issues: Issue[]
  suggestedWeights: WeightSuggestion[]
  signals: Signals
  sections: Outlines
  meta: ScoringMeta
  /** Something is missing: see `error` and `warnings`. */
  partial: boolean
  /** The analysis call failed: requirements are real, nothing after them is. */
  error: string | null
  warnings: string[]
}

export interface ReviewInput {
  rfp: string
  proposal: string
  criteria: Criterion[]
}
