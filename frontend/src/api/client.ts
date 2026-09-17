import type { Criterion, Review, WeightSuggestion } from "@/api/schema"
import { SAMPLES, type SampleId } from "@/api/fixtures/documents"
import { REVIEWS } from "@/api/fixtures/reviews"

/** Real API by default. Authored fixtures require explicit VITE_REVIEW_MODE=fixture.
 * No silent fallback to fixtures after API errors. All calls stay in this client.
 */

export const FIXTURE_MODE = import.meta.env.VITE_REVIEW_MODE === "fixture"
const API_BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000/api").replace(/\/$/, "")

const FIXTURE_LATENCY = { step: 420, jitter: 160 }

export class ReviewError extends Error {
  code: "empty-input" | "unknown-document" | "transport" | "upstream"

  constructor(message: string, code: ReviewError["code"]) {
    super(message)
    this.name = "ReviewError"
    this.code = code
  }
}

/** The trace a run emits. Mirrors the n8n node sequence it will become. */
export const RUN_STEPS = FIXTURE_MODE ? [
  { id: "read-r", label: "Reading the RFP" },
  { id: "extract", label: "Extracting client requirements" },
  { id: "collate", label: "Collating the draft against them" },
  { id: "score", label: "Scoring the criteria" },
  { id: "fixes", label: "Drafting suggested fixes" },
] as const : [{ id: "live-review", label: "Extracting requirements, reviewing and validating evidence" }] as const

export interface RunOptions {
  onStep?: (index: number) => void
  signal?: AbortSignal
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener("abort", () => {
      clearTimeout(t)
      reject(new DOMException("aborted", "AbortError"))
    })
  })

const normalise = (s: string) => s.replace(/\s+/g, " ").trim()

/** Which sample is on the table. Replaced by the model once one is wired up. */
function identify(proposal: string): SampleId | null {
  const needle = normalise(proposal)
  const ids = Object.keys(SAMPLES) as SampleId[]
  return ids.find((id) => normalise(SAMPLES[id].text) === needle) ?? null
}

export async function runReview(
  input: { rfp: string; proposal: string; criteria: Criterion[] },
  opts: RunOptions = {},
): Promise<Review> {
  if (!input.rfp.trim() || !input.proposal.trim()) {
    throw new ReviewError(
      "Both the RFP and the draft proposal are needed before a review can run.",
      "empty-input",
    )
  }

  if (!FIXTURE_MODE) {
    opts.onStep?.(0)
    const controller = new AbortController()
    const cancel = () => controller.abort()
    opts.signal?.addEventListener("abort", cancel, { once: true })
    if (opts.signal?.aborted) controller.abort()
    const timeout = setTimeout(cancel, 210_000)
    try {
      const response = await fetch(`${API_BASE}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
        signal: controller.signal,
      })
      const body = await response.json()
      if (!response.ok) {
        throw new ReviewError(body.error?.message || "The review failed validation. Please retry.", "upstream")
      }
      if (body.schema_version !== "1.0" || !Array.isArray(body.requirements) ||
          !Array.isArray(body.criteria) || !Array.isArray(body.issues) ||
          !Number.isFinite(body.overall) || !["ready", "fix", "not-ready"].includes(body.verdict)) {
        throw new ReviewError("The backend returned an unsupported review contract.", "upstream")
      }
      return body as Review
    } catch (error) {
      if (error instanceof ReviewError) throw error
      throw new ReviewError(controller.signal.aborted
        ? "The review was cancelled or timed out. Please retry."
        : "Cannot reach the review backend. Check the API URL and try again.", "transport")
    } finally {
      clearTimeout(timeout)
      opts.signal?.removeEventListener("abort", cancel)
    }
  }

  const sample = identify(input.proposal)
  if (!sample) {
    throw new ReviewError(
      "This build runs on the sample set only — no model is wired up yet. Load one of the four sample responses to see a full review.",
      "unknown-document",
    )
  }

  for (let i = 0; i < RUN_STEPS.length; i++) {
    opts.onStep?.(i)
    await wait(
      FIXTURE_LATENCY.step + Math.random() * FIXTURE_LATENCY.jitter,
      opts.signal,
    )
  }

  return REVIEWS[sample]
}

export async function suggestWeights(
  _rfp: string,
  opts: { signal?: AbortSignal } = {},
): Promise<WeightSuggestion[]> {
  await wait(900, opts.signal)
  const ids = ["c-problem", "c-scope", "c-pricing", "c-timeline", "c-completeness", "c-tone", "c-risk"]
  return ids.map((criterionId) => ({ criterionId, weight: 100 / ids.length,
    reason: "Equal-weight application default; not inferred from the RFP or an external standard." }))
}
