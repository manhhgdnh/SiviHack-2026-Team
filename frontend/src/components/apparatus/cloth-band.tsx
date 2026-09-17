import { cn } from "@/lib/utils"
import type { Verdict } from "@/api/schema"
import { NO_VERDICT_LABEL, VERDICT_LABEL } from "@/lib/score"

import { useSteppedNumber } from "./stepped-number"

const CLOTH: Record<Verdict, string> = {
  ready: "bg-cloth-ready",
  fix: "bg-cloth-fix",
  "not-ready": "bg-cloth-stop",
}

/**
 * The verdict is bookcloth at page scale, and the traffic light is the binding
 * itself rather than a dot. The judgment is the poster element; the score is a
 * bound numeral subordinate to it, at its left. Ink is the cloth of no verdict:
 * when nothing was scored the band says so, never one of the three colours.
 */
export function ClothBand({
  verdict,
  score,
  note,
  children,
}: {
  verdict: Verdict | null
  score: number | null
  /** One line under the verdict: the requirement tally. */
  note?: React.ReactNode
  children?: React.ReactNode
}) {
  const shown = useSteppedNumber(score ?? 0)

  return (
    <div
      className={cn(
        "text-cloth-text transition-colors duration-500",
        verdict ? CLOTH[verdict] : "bg-ink",
      )}
    >
      <div className="mx-auto flex max-w-[112rem] flex-col gap-4 px-5 py-4 sm:px-8 md:flex-row md:items-center md:gap-6 md:py-5">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-5">
          <span
            className="bg-ink/20 flex shrink-0 items-baseline gap-0.5 px-2.5 py-1.5"
            aria-label={
              score === null
                ? "Overall score not available"
                : `Overall score ${shown.toFixed(1)} out of 5`
            }
          >
            <span
              data-numeric
              aria-hidden
              className="font-sans text-[1.5rem] leading-none font-semibold tabular-nums"
            >
              {score === null ? "—" : shown.toFixed(1)}
            </span>
            <span
              aria-hidden
              className="text-cloth-text/85 font-sans text-[0.8rem] font-semibold"
            >
              /5
            </span>
          </span>

          <div className="min-w-0 flex-1">
            <h1
              className="hand-condensed leading-[0.9] font-semibold uppercase"
              style={{
                fontSize: "clamp(1.75rem, 3.4vw, 3.25rem)",
                letterSpacing: "-0.035em",
              }}
            >
              {verdict ? VERDICT_LABEL[verdict] : NO_VERDICT_LABEL}
            </h1>
            {note && (
              <p className="editorial text-cloth-text/85 mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                {note}
              </p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">{children}</div>
      </div>
    </div>
  )
}
