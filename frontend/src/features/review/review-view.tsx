import { useState } from "react"
import { Pencil, RotateCw } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Criterion, Issue, Review, Verdict, Witness } from "@/api/schema"
import { ClothBand } from "@/components/apparatus/cloth-band"
import { WitnessPane } from "@/components/apparatus/witness-pane"
import { CitationRef } from "@/components/apparatus/citation-ref"
import { useCollation } from "@/components/apparatus/collation"

import {
  CriteriaPanel,
  IssuesPanel,
  RequirementsPanel,
  type IssueVerdict,
} from "./apparatus"

type Panel = "issues" | "requirements" | "criteria"

/**
 * The three must-fix entries sit above the fold, uncollapsed. Nothing that
 * matters most is hidden behind a tab.
 */
function MustFixLede({ issues }: { issues: Issue[] }) {
  const { collate, sourceId } = useCollation()
  const top = issues.filter((i) => i.severity === "must").slice(0, 3)
  if (top.length === 0) return null

  return (
    <section className="border-ink bg-paper border-b-2">
      <div className="mx-auto max-w-[112rem] px-5 py-4 sm:px-8">
        <h2 className="editorial text-ink-2 mb-2.5">
          Fix these first
        </h2>
        <ul className="grid gap-x-8 gap-y-2.5 md:grid-cols-3">
          {top.map((issue, i) => {
            const live = sourceId === `iss-${issue.id}`
            return (
              <li key={issue.id} className="grid grid-cols-[1.5rem_1fr] gap-x-2">
                <span
                  data-numeric
                  aria-hidden
                  className="text-ink-3 pt-[0.15rem] text-right font-sans text-[0.7rem] tabular-nums"
                >
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <button
                    type="button"
                    onClick={() =>
                      collate(`iss-${issue.id}`, [issue.location, issue.against])
                    }
                    className={cn(
                      "cursor-pointer text-left font-serif text-[0.95rem] leading-snug",
                      "hover:text-ink transition-colors",
                      live ? "text-ink" : "text-ink",
                    )}
                  >
                    {issue.lemma}
                  </button>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <CitationRef
                      citation={issue.location}
                      sourceId={`iss-${issue.id}`}
                      also={[issue.against]}
                    />
                    {issue.against && (
                      <CitationRef
                        citation={issue.against}
                        sourceId={`iss-${issue.id}`}
                        also={[issue.location]}
                      />
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

const PANELS: { id: Panel; label: string }[] = [
  { id: "issues", label: "Issues" },
  { id: "requirements", label: "Requirements" },
  { id: "criteria", label: "Criteria" },
]

export function ReviewView({
  review,
  criteria,
  onCriteria,
  witnesses,
  score,
  verdict,
  verdicts,
  onVerdict,
  onEdit,
  onRerun,
  rerunning,
  stale,
  appliedFixes,
  onApply,
  onRevert,
}: {
  review: Review
  criteria: Criterion[]
  onCriteria?: (next: Criterion[]) => void
  witnesses: { R: Witness; P: Witness }
  score: number
  verdict: Verdict
  verdicts: Record<string, IssueVerdict>
  onVerdict: (id: string, next: IssueVerdict) => void
  onEdit: () => void
  onRerun: () => void
  rerunning: boolean
  /** The draft has changed since this review ran, so citations may have moved. */
  stale: boolean
  appliedFixes: Record<string, boolean>
  onApply: (issue: Issue) => void
  onRevert: (issue: Issue) => void
}) {
  const [panel, setPanel] = useState<Panel>("issues")

  const counts = {
    issues: review.issues.filter((i) => (verdicts[i.id] ?? "open") === "open")
      .length,
    requirements: review.requirements.length,
    criteria: criteria.filter((c) => c.enabled).length,
  }

  return (
    <div className="flex min-h-svh flex-col xl:h-svh xl:overflow-hidden">
      <ClothBand verdict={verdict} score={score}>
        <button
          type="button"
          onClick={onEdit}
          className={cn(
            "editorial border-cloth-text/40 text-cloth-text/90 inline-flex cursor-pointer items-center gap-2 border px-4 py-3",
            "hover:bg-cloth-text/12 hover:text-cloth-text transition-colors",
          )}
        >
          <Pencil className="size-3.5" />
          Edit the draft
        </button>
        <button
          type="button"
          onClick={onRerun}
          disabled={rerunning}
          className={cn(
            "editorial bg-cloth-text text-ink inline-flex cursor-pointer items-center gap-2 px-4 py-3",
            "transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          <RotateCw className={cn("size-3.5", rerunning && "animate-spin")} />
          Re-run
        </button>
      </ClothBand>

      {stale && (
        <div role="status" className="border-ink bg-lemma border-b">
          <div className="mx-auto flex max-w-[112rem] flex-wrap items-center justify-between gap-3 px-5 py-2.5 sm:px-8">
            <p className="text-ink text-[0.9rem]">
              The draft has changed since this review ran. Line numbers in the
              citations below may no longer line up.
            </p>
            <button
              type="button"
              onClick={onRerun}
              disabled={rerunning}
              className="editorial border-ink text-ink hover:bg-ink hover:text-paper cursor-pointer border px-3 py-1.5 transition-colors disabled:opacity-50"
            >
              Re-run against the edited draft
            </button>
          </div>
        </div>
      )}

      {review.notifications && review.notifications.length > 0 && (
        <div role="alert" className="border-b border-red-400 bg-red-50 px-5 py-3 text-red-900">
          <strong>{review.notifications.length} explicit RFP contradiction(s)</strong>
          {review.notifications.map((item) => (
            <button key={item.requirement_id} type="button" className="ml-4 underline" onClick={() => {
              setPanel("requirements")
              requestAnimationFrame(() => document.getElementById(item.anchor_id)?.scrollIntoView({ block: "center" }))
            }}>{item.requirement_id}: {item.message}</button>
          ))}
        </div>
      )}
      {review.readiness && <p className="border-b px-5 py-2 text-sm">
        <strong>{review.readiness.replaceAll("_", " ")}</strong> — {review.readiness_reasons?.join(" ")}
      </p>}
      <MustFixLede issues={review.issues} />

      <div className="grid min-h-0 flex-1 xl:grid-cols-[1.15fr_1fr_1fr]">
        <div className="border-rule flex min-h-0 min-w-0 flex-col xl:border-r">
          <nav
            className="border-rule flex shrink-0 gap-0 border-b"
            aria-label="Review sections"
          >
            {PANELS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setPanel(p.id)}
                aria-current={panel === p.id}
                className={cn(
                  "editorial relative cursor-pointer px-4 py-3 transition-colors",
                  panel === p.id
                    ? "text-ink"
                    : "text-ink-3 hover:text-ink-2",
                )}
              >
                {p.label}
                <span
                  data-numeric
                  className="ml-1.5 tabular-nums opacity-60"
                >
                  {counts[p.id]}
                </span>
                {panel === p.id && (
                  <span
                    aria-hidden
                    className="bg-ink absolute inset-x-0 -bottom-px h-[2px]"
                  />
                )}
              </button>
            ))}
          </nav>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 sm:px-6">
            {panel === "issues" && (
              <IssuesPanel
                issues={review.issues}
                criteria={criteria}
                verdicts={verdicts}
                onVerdict={onVerdict}
                appliedFixes={appliedFixes}
                onApply={onApply}
                onRevert={onRevert}
              />
            )}
            {panel === "requirements" && (
              <RequirementsPanel requirements={review.requirements} counters={review.counters} />
            )}
            {panel === "criteria" && (
              <CriteriaPanel
                criteria={criteria}
                scores={review.criteria}
                onCriteria={onCriteria}
              />
            )}
          </div>
        </div>

        <WitnessPane
          witness={witnesses.R}
          className="border-rule min-h-[22rem] border-t xl:min-h-0 xl:border-t-0 xl:border-r"
        />
        <WitnessPane
          witness={witnesses.P}
          className="border-rule min-h-[22rem] border-t xl:min-h-0 xl:border-t-0"
        />
      </div>
    </div>
  )
}
