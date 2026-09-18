import type {
  ConstraintKind,
  CoverageStatus,
  DocOutline,
  FindingType,
  ScoringResult,
  Severity as Graded,
  Source,
  WeightSuggestion as Suggested,
} from "@/api/generated/types.gen"
import type {
  Citation,
  Constraint,
  CriterionId,
  CriterionScore,
  Issue,
  Requirement,
  RequirementStatus,
  Review,
  Severity,
  Signal,
  WeightSuggestion,
} from "@/api/schema"
import { excerpt, plain } from "@/lib/quote"
import { verdictFor } from "@/lib/score"

/**
 * The backend speaks in requirements, coverage, violations, findings and scores. The
 * edition speaks in issues, each with a lemma and a citation. This is the one place the two
 * vocabularies meet, and every mapping is a table, not a rule.
 */

/** Which criterion a finding is filed under: the scoring group that owns its type. */
export const FINDING_CRITERION: Record<FindingType, CriterionId> = {
  OVERCOMMIT: "risk_transparency",
  SCOPE_CREEP: "scope_clarity",
  UNREALISTIC_TIMELINE: "timeline_clarity",
  PRICING_MISMATCH: "pricing_clarity",
  VAGUENESS: "scope_clarity",
  INCONSISTENCY: "problem_understanding",
}

export const CONSTRAINT_CRITERION: Record<ConstraintKind, CriterionId> = {
  BUDGET: "pricing_clarity",
  DEADLINE: "timeline_clarity",
  TECHNOLOGY: "scope_clarity",
  SCOPE: "scope_clarity",
  LEGAL: "risk_transparency",
  OTHER: "risk_transparency",
}

const SEVERITY: Record<Graded, Severity> = { HIGH: "must", MEDIUM: "should", LOW: "optional" }
const STATUS: Record<CoverageStatus, RequirementStatus> = {
  ADDRESSED: "addressed",
  PARTIAL: "partial",
  MISSING: "missing",
  CONTRADICTED: "contradicted",
}
const GAP_SEVERITY: Record<CoverageStatus, Severity> = {
  ADDRESSED: "optional",
  PARTIAL: "should",
  MISSING: "must",
  CONTRADICTED: "must",
}
const SEVERITY_ORDER: Severity[] = ["must", "should", "optional"]
const KIND_ORDER: Issue["kind"][] = ["violation", "coverage", "finding"]

type Cite = (
  source: Source,
  sectionId: string | null | undefined,
  quote: string | null | undefined,
  grounding?: string | null,
) => Citation

/** Citations resolve their header through the outline, so a chip reads `§3.1 · Pricing`. */
function citer(outlines: { rfp: DocOutline; proposal: DocOutline }): Cite {
  return (source, sectionId, quote, grounding) => {
    const id = sectionId ?? ""
    const header = id ? (outlines[source].sections.find((s) => s.id === id)?.header ?? "") : ""
    return {
      witness: source === "rfp" ? "R" : "P",
      sectionId: id,
      header,
      label: id ? (header ? `${id} · ${header}` : id) : "",
      quote: quote ?? null,
      fuzzy: grounding === "fuzzy",
    }
  }
}

export function adapt(r: ScoringResult): Review {
  const cite = citer(r.sections)
  const reqById = new Map(r.requirements.map((q) => [q.id, q]))
  const conById = new Map(r.constraints.map((c) => [c.id, c]))
  const covByReq = new Map(r.coverage.map((c) => [c.requirementId, c]))

  const requirements: Requirement[] = r.requirements.map((q) => {
    const cov = covByReq.get(q.id)
    const source = cite("rfp", q.section, q.rfpQuote, q.grounding)
    return {
      id: q.id,
      label: q.label,
      section: source.header || "RFP",
      text: plain(q.rfpQuote),
      status: cov ? STATUS[cov.status] : "missing",
      answeredAt: cov?.proposalSection
        ? cite("proposal", cov.proposalSection, cov.proposalQuote, cov.grounding)
        : null,
      source,
      note: cov ? (cov.explanation ?? "") : "The model returned no verdict for this requirement.",
    }
  })

  const constraints: Constraint[] = r.constraints.map((c) => ({
    id: c.id,
    kind: c.kind,
    label: c.label,
    source: cite("rfp", c.section, c.rfpQuote, c.grounding),
  }))

  const issues: Issue[] = []
  for (const v of r.constraintViolations) {
    const con = conById.get(v.constraintId)
    issues.push({
      id: `vio-${v.constraintId}`,
      kind: "violation",
      severity: "must",
      criterionId: con ? CONSTRAINT_CRITERION[con.kind] : "risk_transparency",
      constraintId: v.constraintId,
      constraintKind: con?.kind ?? "OTHER",
      graded: SEVERITY[v.severity],
      lemma: excerpt(v.proposalQuote),
      quoted: plain(v.proposalQuote),
      location: cite("proposal", v.proposalSection, v.proposalQuote, v.grounding),
      against: con ? cite("rfp", con.section, con.rfpQuote, con.grounding) : null,
      whyItMatters: v.violation,
      suggestedFix: v.fix,
    })
  }
  for (const c of r.coverage) {
    if (c.status === "ADDRESSED") continue
    const q = reqById.get(c.requirementId)
    const label = q?.label ?? c.requirementId
    issues.push({
      id: `cov-${c.requirementId}`,
      kind: "coverage",
      status: STATUS[c.status] as Exclude<RequirementStatus, "addressed">,
      requirementId: c.requirementId,
      severity: GAP_SEVERITY[c.status],
      criterionId: "completeness",
      lemma: c.proposalQuote
        ? excerpt(c.proposalQuote)
        : `nothing on ${label.charAt(0).toLowerCase()}${label.slice(1)}`,
      quoted: c.proposalQuote ? plain(c.proposalQuote) : null,
      location: c.proposalSection
        ? cite("proposal", c.proposalSection, c.proposalQuote, c.grounding)
        : null,
      against: q ? cite("rfp", q.section, q.rfpQuote, q.grounding) : null,
      whyItMatters: c.explanation ?? "",
      suggestedFix: c.fix,
    })
  }
  r.findings.forEach((f, i) => {
    issues.push({
      id: `fin-${i + 1}`,
      kind: "finding",
      findingType: f.type,
      severity: SEVERITY[f.severity],
      criterionId: FINDING_CRITERION[f.type],
      lemma: excerpt(f.proposalQuote),
      quoted: plain(f.proposalQuote),
      location: cite("proposal", f.location, f.proposalQuote, f.grounding),
      against: null,
      whyItMatters: f.explanation,
      suggestedFix: f.fix,
    })
  })
  issues.sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) ||
      KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind),
  )

  const criteria: CriterionScore[] = r.scores.map((s) => ({
    criterionId: s.id,
    score: s.score,
    strength: s.strengths,
    weakness: s.weaknesses,
    note: s.note,
    citations: s.citations.map((c) => cite(c.source, c.section, c.quote, c.grounding)),
  }))

  // Code-derived signals as evidence: an amount belongs beside Pricing, a date beside
  // Timeline, and a vague phrase beside whichever of the two owns its section (else Scope).
  const evidence: Partial<Record<CriterionId, Signal[]>> = {}
  const add = (id: CriterionId, s: Signal) => {
    ;(evidence[id] ??= []).push(s)
  }
  for (const m of r.signals.pricing.mentions) {
    add("pricing_clarity", { kind: "amount", value: m.value, citation: cite("proposal", m.section, m.value) })
  }
  for (const m of r.signals.timeline.mentions) {
    add("timeline_clarity", { kind: "date", value: m.value, citation: cite("proposal", m.section, m.value) })
  }
  for (const v of r.signals.vaguePhrases) {
    const owner: CriterionId =
      v.section && r.signals.pricing.sections.includes(v.section)
        ? "pricing_clarity"
        : v.section && r.signals.timeline.sections.includes(v.section)
          ? "timeline_clarity"
          : "scope_clarity"
    add(owner, { kind: "vague", value: v.phrase, citation: cite("proposal", v.section, v.phrase) })
  }

  return {
    overall: r.overall,
    verdict: verdictFor(r.overall),
    criteria,
    requirements,
    constraints,
    issues,
    suggestedWeights: adaptSuggestions(r.suggestedWeights),
    signals: r.signals,
    evidence,
    sections: r.sections,
    meta: r.meta,
    partial: r.partial,
    error: r.error,
    warnings: r.warnings,
  }
}

/**
 * Backend weights are relative (1 = neutral); the UI's are shares of 100. Exact shares
 * here; the app's `rebalance()` settles them to integers that total 100.
 */
export function adaptSuggestions(s: Suggested[]): WeightSuggestion[] {
  const total = s.reduce((sum, x) => sum + x.weight, 0)
  if (total <= 0) return []
  return s.map((x) => ({ criterionId: x.criterionId, weight: (x.weight / total) * 100, reason: x.reason }))
}
