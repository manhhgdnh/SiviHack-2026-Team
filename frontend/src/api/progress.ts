import type {
  CoverageEvent,
  FindingsEvent,
  Outlines,
  ProgressEvent,
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
  /** The backend's live notes: what it is doing inside the stage it is working on. */
  notes: ProgressEvent[]
  sections?: Outlines
  requirements?: RequirementsEvent
  coverage?: CoverageEvent
  scores?: ScoresEvent
  findings?: FindingsEvent
  result?: ScoringResult
  review?: Review
}

export const EMPTY_PROGRESS: ReviewProgress = { stage: "connecting", notes: [] }

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
    case "progress":
      return { ...acc, notes: [...acc.notes.slice(-19), frame.data] }
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
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
  let elapsed = 0
  const note = (stage: string, message: string): StreamEvent => {
    elapsed += 400
    return { event: "progress", data: { stage, message, elapsedMs: elapsed } }
  }
  const hasRfp = r.requirements.length > 0 || r.constraints.length > 0
  const frames: StreamEvent[] = [
    { event: "sections", data: r.sections },
    ...(hasRfp
      ? [
          note(
            "requirements",
            `Split the RFP into ${plural(r.sections.rfp.count, "section")} and the draft into ${plural(r.sections.proposal.count, "section")}; asking the model for the client's requirements and constraints…`,
          ),
          note(
            "requirements",
            `Verified ${plural(r.requirements.length + r.constraints.length, "RFP quote")} against the text — answered from the recording`,
          ),
        ]
      : []),
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
      note(
        "coverage",
        hasRfp
          ? `Checking ${plural(r.requirements.length, "requirement")} and ${plural(r.constraints.length, "constraint")} against the draft…`
          : "No RFP: nothing to check coverage against; skipping to the scores",
      ),
      { event: "coverage", data: { coverage: r.coverage, constraintViolations: r.constraintViolations } },
      note("scores", "Scoring 6 criteria in 3 parallel groups: understanding, commercials, risk…"),
      note("scores", "understanding scored: 2 criteria"),
      note("scores", "commercials scored: 3 criteria"),
      note("scores", "risk scored: 1 criterion"),
      { event: "scores", data: { scores: r.scores, overall: r.overall } },
      note("findings", `Verified ${plural(r.findings.length, "finding quote")} and the score citations; computing the overall from your weights`),
      { event: "findings", data: { findings: r.findings } },
    )
  }
  frames.push({ event: "done", data: r })
  return frames
}
