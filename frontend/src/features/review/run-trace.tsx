import { cn } from "@/lib/utils"
import { FIXTURE_MODE, RUN_STEPS } from "@/api/client"

/**
 * The run takes time and can fail, so it shows its work. Nothing here is a
 * spinner over a blank page: the steps are the same sequence the n8n trace
 * will stream once it exists.
 */
export function RunTrace({ active }: { active: number }) {
  return (
    <div className="mx-auto flex min-h-svh w-full max-w-[42rem] flex-col justify-center px-5 py-16">
      <h2 className="hand-condensed text-ink text-[1.6rem] leading-tight font-semibold tracking-tight uppercase">
        Collating the draft against the RFP
      </h2>
      <p className="text-ink-2 mt-1.5 text-[0.85rem]">
        Results appear after both model calls and evidence validation complete.
        Longer documents may take several minutes.
      </p>

      <ol className="border-rule mt-7 border-t">
        {RUN_STEPS.map((step, i) => {
          const done = i < active
          const running = i === active

          return (
            <li
              key={step.id}
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
                {done ? "done" : running ? "running" : "waiting"}
              </span>

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

      <p className="text-ink-3 mt-4 font-sans text-[0.72rem]">
        {FIXTURE_MODE ? "Demo fixture mode: authored sample findings; no model is called." : "Live Gemini review. Invalid or incomplete evidence is rejected."}
      </p>
    </div>
  )
}
