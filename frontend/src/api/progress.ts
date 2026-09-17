import type {
  CoverageEvent,
  FindingsEvent,
  Outlines,
  RequirementsEvent,
  ScoresEvent,
  ScoringResult,
  StreamEvent,
} from "@/api/generated/types.gen"
import type { Review } from "@/api/schema"
import { adapt } from "@/api/adapt"
import { ReviewError } from "@/api/errors"

export type Stage =
  | "connecting"
  | "sections"
  | "requirements"
  | "coverage"
  | "scores"
  | "findings"
  | "done"

/** The trace rows, in the order the backend emits its frames. */
export const STAGES = [
  { id: "sections", label: "Reading the documents" },
  { id: "requirements", label: "Extracting client requirements" },
  { id: "coverage", label: "Collating the draft against them" },
  { id: "scores", label: "Scoring the criteria" },
  { id: "findings", label: "Drafting suggested fixes" },
] as const

/** What has arrived so far. `review` exists exactly when `stage === "done"`. */
export interface ReviewProgress {
  stage: Stage
  sections?: Outlines
  requirements?: RequirementsEvent
  coverage?: CoverageEvent
  scores?: ScoresEvent
  findings?: FindingsEvent
  result?: ScoringResult
  review?: Review
}

export const EMPTY_PROGRESS: ReviewProgress = { stage: "connecting" }

/** Index into STAGES of the step running now (STAGES.length once done). */
export function activeStep(p: ReviewProgress): number {
  if (p.stage === "connecting") return 0
  if (p.stage === "done") return STAGES.length
  return STAGES.findIndex((s) => s.id === p.stage) + 1
}

export function reduceProgress(acc: ReviewProgress, frame: StreamEvent): ReviewProgress {
  switch (frame.event) {
    case "sections":
      return { ...acc, stage: "sections", sections: frame.data }
    case "requirements":
      return { ...acc, stage: "requirements", requirements: frame.data }
    case "coverage":
      return { ...acc, stage: "coverage", coverage: frame.data }
    case "scores":
      return { ...acc, stage: "scores", scores: frame.data }
    case "findings":
      return { ...acc, stage: "findings", findings: frame.data }
    case "done":
      return { ...acc, stage: "done", result: frame.data, review: adapt(frame.data) }
    case "error":
      // stream.ts throws before this is reached; kept so the switch is exhaustive.
      throw new ReviewError(
        `The review failed during "${frame.data.stage}": ${frame.data.error}`,
        "upstream",
        frame.data.stage,
      )
  }
}

/**
 * A finished result replayed as the frames the backend would have sent, including the
 * degraded path: when the analysis call failed (`error` set) `done` follows `requirements`.
 */
export function eventsFrom(r: ScoringResult): StreamEvent[] {
  const frames: StreamEvent[] = [
    { event: "sections", data: r.sections },
    {
      event: "requirements",
      data: {
        requirements: r.requirements,
        constraints: r.constraints,
        suggestedWeights: r.suggestedWeights,
        extractCached: r.meta.extractCached,
      },
    },
  ]
  if (!r.error) {
    frames.push(
      { event: "coverage", data: { coverage: r.coverage, constraintViolations: r.constraintViolations } },
      { event: "scores", data: { scores: r.scores, overall: r.overall } },
      { event: "findings", data: { findings: r.findings } },
    )
  }
  frames.push({ event: "done", data: r })
  return frames
}
