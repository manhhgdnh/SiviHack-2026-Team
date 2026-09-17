import { cn } from "@/lib/utils"
import { MOCK } from "@/api/client"
import { activeStep, STAGES, type ReviewProgress } from "@/api/progress"

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
const join = (parts: string[]) => parts.join(" · ")

/** What a finished stage found, from the frame it produced. Nothing here is on a timer. */
function ticker(stage: (typeof STAGES)[number]["id"], p: ReviewProgress, hasRfp: boolean): string | null {
  if (!hasRfp && (stage === "requirements" || stage === "coverage")) return "no RFP"
  if (stage === "requirements" && p.requirements) {
    const n = p.requirements.requirements.length
    const m = p.requirements.constraints.length
    if (n === 0 && m === 0) return "nothing extracted from the RFP"
    return join([plural(n, "requirement"), ...(m ? [plural(m, "constraint")] : [])])
  }
  if (stage === "coverage" && p.coverage) {
    const contradicted = p.coverage.coverage.filter((c) => c.status === "CONTRADICTED").length
    const missing = p.coverage.coverage.filter((c) => c.status === "MISSING").length
    const violations = p.coverage.constraintViolations.length
    const parts = [
      ...(contradicted ? [`${contradicted} contradicted`] : []),
      ...(missing ? [`${missing} not found`] : []),
      ...(violations ? [plural(violations, "violation")] : []),
    ]
    return parts.length ? join(parts) : "every requirement addressed"
  }
  if (stage === "findings" && p.findings) {
    const n = p.findings.findings.length
    return n === 0 ? "no findings" : plural(n, "finding")
  }
  return null
}

/**
 * The run takes time and can fail, so it shows its work. Each row is a stage the backend
 * reports as it finishes, with what it found printed beneath it, so the wait is evidence
 * arriving rather than a spinner over a blank page.
 */
export function RunTrace({
  progress,
  hasRfp,
  onStop,
}: {
  progress: ReviewProgress
  hasRfp: boolean
  onStop: () => void
}) {
  const active = activeStep(progress)

  return (
    <div className="mx-auto flex min-h-svh w-full max-w-[42rem] flex-col justify-center px-5 py-16">
      <h2 className="hand-condensed text-ink text-[1.6rem] leading-tight font-semibold tracking-tight uppercase">
        {hasRfp ? "Collating the draft against the RFP" : "Scoring the draft on its own"}
      </h2>
      <p className="text-ink-2 mt-1.5 text-[0.85rem]">
        {MOCK
          ? "Replaying a recorded review, one stage at a time."
          : "Each stage reports as it finishes. Usually under a minute on the hosted model; a local model can take several."}
      </p>

      <ol className="border-rule mt-7 border-t" aria-label="Run progress">
        {STAGES.map((step, i) => {
          const done = i < active
          const running = i === active
          const skipped = done && !hasRfp && (step.id === "requirements" || step.id === "coverage")
          const found = done ? ticker(step.id, progress, hasRfp) : null

          return (
            <li
              key={step.id}
              aria-current={running ? "step" : undefined}
              className="border-rule-hair grid grid-cols-[2rem_1fr_auto] items-baseline gap-x-3 border-b py-3"
            >
              <span
                data-numeric
                aria-hidden
                className={cn(
                  "text-right font-sans text-[0.7rem] tabular-nums",
                  running ? "text-ink font-semibold" : "text-ink-3",
                )}
              >
                {i + 1}
              </span>

              <span
                className={cn(
                  "text-[0.9rem] leading-snug",
                  done && "text-ink-2",
                  running && "text-ink font-semibold",
                  !done && !running && "text-ink-3",
                )}
              >
                {step.label}
              </span>

              <span
                className={cn(
                  "editorial",
                  done && "text-ink-2",
                  running && "text-ink",
                  !done && !running && "text-ink-3/60",
                )}
              >
                {skipped ? "skipped" : done ? "done" : running ? "running" : "waiting"}
              </span>

              {found && (
                <p
                  role="status"
                  data-numeric
                  className="text-ink-2 col-start-2 col-end-4 mt-1 font-sans text-[0.8rem] tabular-nums"
                >
                  {found}
                </p>
              )}

              {running && (
                <span
                  aria-hidden
                  className="col-start-2 col-end-4 mt-1.5 block h-[2px] w-full overflow-hidden bg-rule-hair"
                >
                  <span className="bg-ink block h-full w-1/3 animate-[trace-sweep_1.1s_ease-in-out_infinite]" />
                </span>
              )}
            </li>
          )
        })}
      </ol>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-ink-3 font-sans text-[0.72rem]">
          {MOCK
            ? "Running on recorded results in the backend's shape. No model is called in this build."
            : "Stages advance as the backend reports them; nothing here is on a timer."}
        </p>
        <button
          type="button"
          onClick={onStop}
          className="editorial border-ink text-ink hover:bg-ink hover:text-paper cursor-pointer border px-3 py-1.5 transition-colors"
        >
          Stop the run
        </button>
      </div>
    </div>
  )
}
