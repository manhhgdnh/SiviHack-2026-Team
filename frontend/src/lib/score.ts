import type { Criterion, CriterionScore, Verdict, Weights } from "@/api/schema"

/**
 * Weights are shares of a fixed 100 and they compete: raising one takes from
 * the others on screen, so the budget is visible rather than implied.
 */
export function redistribute(criteria: Criterion[], id: string, next: number): Criterion[] {
  const target = Math.max(0, Math.min(100, Math.round(next)))
  const enabled = criteria.filter((c) => c.enabled)
  const others = enabled.filter((c) => c.id !== id)

  if (others.length === 0) {
    return criteria.map((c) => (c.id === id ? { ...c, weight: 100 } : c))
  }

  const remaining = 100 - target
  const othersTotal = others.reduce((sum, c) => sum + c.weight, 0)

  const raw = new Map<string, number>()
  for (const c of others) {
    raw.set(c.id, othersTotal > 0 ? (c.weight / othersTotal) * remaining : remaining / others.length)
  }

  return settle(
    criteria.map((c) =>
      c.id === id ? { ...c, weight: target } : c.enabled ? { ...c, weight: raw.get(c.id) ?? 0 } : c,
    ),
    id,
  )
}

/** Re-balance after a toggle, so enabled weights always total exactly 100. */
export function rebalance(criteria: Criterion[]): Criterion[] {
  const enabled = criteria.filter((c) => c.enabled)
  if (enabled.length === 0) return criteria

  const total = enabled.reduce((sum, c) => sum + c.weight, 0)
  return settle(
    criteria.map((c) =>
      c.enabled ? { ...c, weight: total > 0 ? (c.weight / total) * 100 : 100 / enabled.length } : c,
    ),
  )
}

/** Largest-remainder rounding, so the printed shares total exactly 100. */
function settle(criteria: Criterion[], pinned?: string): Criterion[] {
  const enabled = criteria.filter((c) => c.enabled)
  if (enabled.length === 0) return criteria

  const floors = new Map<string, number>()
  const remainders: { id: string; rem: number }[] = []

  for (const c of enabled) {
    const f = Math.floor(c.weight)
    floors.set(c.id, f)
    remainders.push({ id: c.id, rem: c.weight - f })
  }

  let deficit = 100 - [...floors.values()].reduce((sum, weight) => sum + weight, 0)

  remainders.sort((a, b) => {
    if (a.id === pinned) return 1
    if (b.id === pinned) return -1
    return b.rem - a.rem
  })

  for (const entry of remainders) {
    if (deficit <= 0) break
    floors.set(entry.id, (floors.get(entry.id) ?? 0) + 1)
    deficit--
  }

  return criteria.map((c) => (c.enabled ? { ...c, weight: floors.get(c.id) ?? 0 } : c))
}

/** The weights as the backend takes them: every criterion, disabled ones at 0. */
export function weightsOf(criteria: Criterion[]): Weights {
  return Object.fromEntries(criteria.map((c) => [c.id, c.enabled ? c.weight : 0])) as Weights
}

/**
 * The backend's own formula (aggregate.weighted_overall): Σ score×weight / Σ weight over the
 * criteria that have a score, two decimals; null when nothing is scored. Dragging a slider
 * recomputes here, so it never costs a model call and lands on the number a re-run returns.
 */
export function overallOf(
  scores: readonly { id: string; score: number | null }[],
  weights: Readonly<Record<string, number>>,
): number | null {
  let num = 0
  let den = 0
  for (const s of scores) {
    if (s.score === null) continue
    const w = weights[s.id] ?? 1
    num += w * s.score
    den += w
  }
  return den > 0 ? Math.round((num / den) * 100) / 100 : null
}

export function weightedScore(criteria: Criterion[], scores: CriterionScore[]): number | null {
  return overallOf(
    scores.map((s) => ({ id: s.criterionId, score: s.score })),
    weightsOf(criteria),
  )
}

export function verdictFor(score: number | null): Verdict | null {
  if (score === null) return null
  if (score >= 4) return "ready"
  if (score >= 2.5) return "fix"
  return "not-ready"
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  ready: "Ready to send",
  fix: "Fix before sending",
  "not-ready": "Not ready",
}

/** The band's word when nothing was scored. */
export const NO_VERDICT_LABEL = "Not scored"
