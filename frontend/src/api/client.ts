import type { RequirementsEvent, ScoreRequest, ScoringResult, StreamEvent } from "@/api/generated/types.gen"
import { zRequirementsEvent, zScoringResult } from "@/api/generated/zod.gen"
import type { ReviewInput, WeightAdvice } from "@/api/schema"
import { adaptSuggestions } from "@/api/adapt"
import { isAbort, ReviewError } from "@/api/errors"
import { eventsFrom } from "@/api/progress"
import { detail, isGateway, streamScore, UNREACHABLE } from "@/api/stream"
import { RFP_TEXT, SAMPLES, type SampleId } from "@/api/fixtures/documents"
import weak from "@/api/fixtures/results/weak.json"
import medium from "@/api/fixtures/results/medium.json"
import strong from "@/api/fixtures/results/strong.json"
import overpromise from "@/api/fixtures/results/overpromise.json"
import { canonical } from "@/lib/quote"
import { overallOf, weightsOf } from "@/lib/score"

/**
 * The one client. Every request in the app originates here or in `stream.ts`, so headers,
 * errors and the mock switch have exactly one home.
 *
 * With `VITE_API_URL` unset this build replays the four recorded results (real backend
 * output for the sample set) as the same six frames the backend streams. Set it to `/api`
 * for the Vite dev proxy or nginx, and nothing outside this file changes.
 */

const API = (import.meta.env.VITE_API_URL as string | undefined)?.trim() || ""

/** True when this build replays the recorded results instead of calling the backend. */
export const MOCK = API === ""

const MOCK_LATENCY = { step: 420, jitter: 160 }

/** The request as the backend takes it: canonical text, the current weights. */
export function requestFor(input: ReviewInput): ScoreRequest {
  return {
    rfp: canonical(input.rfp),
    proposal: canonical(input.proposal),
    weights: weightsOf(input.criteria),
  }
}

/** One review as typed frames. The proposal is required; without an RFP the backend skips coverage. */
export function streamReview(input: ReviewInput, signal?: AbortSignal): AsyncIterable<StreamEvent> {
  if (!input.proposal.trim()) {
    throw new ReviewError(
      "The draft proposal is empty. Paste it or upload the .md file, then run again.",
      "empty-input",
    )
  }
  return MOCK ? mockStream(input, signal) : streamScore(API, requestFor(input), signal)
}

/** Call 1 only (POST /rfp/extract): the model's weight suggestions for this RFP. */
export async function suggestWeights(rfp: string, signal?: AbortSignal): Promise<WeightAdvice> {
  if (!rfp.trim()) throw new ReviewError("Paste the RFP first.", "empty-input")
  const event = MOCK ? await mockExtract(rfp, signal) : await extractLive(canonical(rfp), signal)
  return {
    suggestions: adaptSuggestions(event.suggestedWeights),
    requirements: event.requirements.length,
    constraints: event.constraints.length,
  }
}

async function extractLive(rfp: string, signal?: AbortSignal): Promise<RequirementsEvent> {
  let res: Response
  try {
    res = await fetch(`${API}/rfp/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rfp }),
      signal,
    })
  } catch (e) {
    if (isAbort(e)) throw e
    throw new ReviewError(UNREACHABLE, "transport")
  }
  if (isGateway(res.status)) throw new ReviewError(UNREACHABLE, "transport")
  if (res.status === 400) throw new ReviewError(await detail(res), "empty-input")
  if (!res.ok) throw new ReviewError(await detail(res), "upstream")
  const parsed = zRequirementsEvent.safeParse(await res.json())
  if (!parsed.success) {
    throw new ReviewError(
      "The review service answered in a shape this build does not understand. Regenerate the client from app/openapi.json.",
      "contract",
    )
  }
  return parsed.data as RequirementsEvent
}

/* ---- mock mode: the recorded results, replayed as the backend would stream them ---------- */

const RECORDED: Record<SampleId, unknown> = { weak, medium, strong, overpromise }
const parsed = new Map<SampleId, ScoringResult>()

/** Validated on first use, so a stale recording fails at the first mock run, not at app start. */
function recorded(id: SampleId): ScoringResult {
  let r = parsed.get(id)
  if (!r) {
    r = zScoringResult.parse(RECORDED[id]) as ScoringResult
    parsed.set(id, r)
  }
  return r
}

const normalise = (s: string) => s.replace(/\s+/g, " ").trim()

/** Which sample is on the table, for the mock build. */
function identify(proposal: string): SampleId | null {
  const needle = normalise(proposal)
  const ids = Object.keys(SAMPLES) as SampleId[]
  return ids.find((id) => normalise(SAMPLES[id].text) === needle) ?? null
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener("abort", () => {
      clearTimeout(t)
      reject(new DOMException("aborted", "AbortError"))
    })
  })

async function* mockStream(input: ReviewInput, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const sample = identify(input.proposal)
  if (!sample) {
    throw new ReviewError(
      "This build replays recorded results for the sample set — no backend is wired up. Load one of the four sample responses, or set VITE_API_URL.",
      "unknown-document",
    )
  }
  const weights = weightsOf(input.criteria)
  const base = recorded(sample)
  // The recording was made with equal weights; apply this run's weights the way the backend would.
  const result: ScoringResult = { ...base, weights, overall: overallOf(base.scores, weights) }
  for (const frame of eventsFrom(result)) {
    await wait(MOCK_LATENCY.step + Math.random() * MOCK_LATENCY.jitter, signal)
    yield frame
  }
}

async function mockExtract(rfp: string, signal?: AbortSignal): Promise<RequirementsEvent> {
  await wait(900, signal)
  if (normalise(rfp) !== normalise(RFP_TEXT)) {
    throw new ReviewError(
      "This build has recorded results for the NordFrame RFP only.",
      "unknown-document",
    )
  }
  const r = recorded("weak") // one RFP → the same extraction for all four samples
  return {
    requirements: r.requirements,
    constraints: r.constraints,
    suggestedWeights: r.suggestedWeights,
    extractCached: true,
  }
}
