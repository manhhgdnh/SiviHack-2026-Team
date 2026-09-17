import { useState } from "react"
import {
  Check,
  ChevronDown,
  Copy,
  Eye,
  FilePlus2,
  Minus,
  Undo2,
} from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import type {
  Criterion,
  CriterionScore,
  Issue,
  Requirement,
  RequirementStatus,
  Severity,
} from "@/api/schema"
import { CitationRef } from "@/components/apparatus/citation-ref"
import { Lemma } from "@/components/apparatus/lemma"
import { useCollation } from "@/components/apparatus/collation"
import { Slider } from "@/components/ui/slider"
import { redistribute } from "@/lib/score"

/* --------------------------------------------------------------------------
   Requirement status uses color and text together; severity remains a separate
   field so a color alone never carries the review judgment.
-------------------------------------------------------------------------- */

const STATUS_STYLE: Record<RequirementStatus, string> = {
  addressed: "text-green-700 font-medium",
  partial: "text-amber-700 font-semibold",
  missing: "text-gray-600 font-medium",
  contradicted: "text-cloth-stop font-bold",
}

const SEVERITY_LABEL: Record<Severity, string> = {
  must: "Must fix",
  should: "Should fix",
  optional: "Optional",
}

const SEVERITY_STYLE: Record<Severity, string> = {
  must: "text-ink font-bold",
  should: "text-ink-2 font-semibold",
  optional: "text-ink-3 font-medium",
}

/** Every entry is numbered in the margin, and every number is a link to it. */
function Ref({ id, n }: { id: string; n: string | number }) {
  return (
    <a
      href={`#${id}`}
      title="Link to this entry"
      data-numeric
      className={cn(
        "text-ink-2 hover:text-ink pt-[0.2rem] text-right font-sans text-[0.8rem] tabular-nums",
        "decoration-rule hover:decoration-ink underline underline-offset-[3px] transition-colors",
      )}
    >
      {n}
    </a>
  )
}

const targeted = (id: string) =>
  typeof location !== "undefined" && location.hash === `#${id}`

/* -------------------------------------------------------------- criteria -- */

function ScoreMarks({ score }: { score: number }) {
  return (
    <span
      className="flex shrink-0 items-center gap-[3px]"
      aria-label={`${score} out of 5`}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={cn("h-3.5 w-[3px]", n <= score ? "bg-ink" : "bg-rule")}
        />
      ))}
    </span>
  )
}

export function CriteriaPanel({
  criteria,
  scores,
  onCriteria,
}: {
  criteria: Criterion[]
  scores: CriterionScore[]
  /** When present, weights become live and the verdict recomputes as they move. */
  onCriteria?: (next: Criterion[]) => void
}) {
  const byId = new Map(criteria.map((c) => [c.id, c]))

  return (
    <ul className="border-rule border-t">
      {scores.map((s, i) => {
        const c = byId.get(s.criterionId)
        if (!c || !c.enabled) return null
        const id = `e-crit-${i + 1}`

        return (
          <li
            key={s.criterionId}
            id={id}
            className="border-rule-hair grid scroll-mt-28 grid-cols-[2rem_1fr] gap-x-3 border-b py-3.5"
          >
            <Ref id={id} n={i + 1} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1.5">
                <Lemma
                  reading={`${s.score}/5`}
                  readingClassName="text-ink font-bold"
                  className="text-[1rem] leading-snug font-semibold"
                >
                  {c.name}
                </Lemma>
                <div className="flex items-center gap-2.5">
                  <ScoreMarks score={s.score} />
                  <span
                    data-numeric
                    className="text-ink-2 w-[2.6rem] text-right font-sans text-[0.8rem] tabular-nums"
                  >
                    {c.weight}%
                  </span>
                </div>
              </div>

              {onCriteria && (
                <div className="mt-2 flex items-center gap-3">
                  <Slider
                    value={[c.weight]}
                    min={0}
                    max={60}
                    step={1}
                    aria-label={`Weight for ${c.name}`}
                    onValueChange={([next]) =>
                      onCriteria(redistribute(criteria, c.id, next))
                    }
                    className="max-w-[16rem] min-w-0 flex-1"
                  />
                  <span className="editorial text-ink-3">share of 100</span>
                </div>
              )}

              {s.strength && (
                <p className="text-ink-2 mt-2 max-w-[68ch] text-[0.9rem] leading-relaxed">
                  {s.strength}
                </p>
              )}
              <p className="text-ink mt-1 max-w-[68ch] text-[0.95rem] leading-relaxed">
                {s.weakness}
              </p>

              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                {s.citations.map((citation, n) => (
                  <CitationRef
                    key={`${s.criterionId}-${n}`}
                    citation={citation}
                    sourceId={`crit-${s.criterionId}-${n}`}
                    also={s.citations.filter((_, m) => m !== n)}
                  />
                ))}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/* ---------------------------------------------------------- requirements -- */

const STATUS_ORDER: RequirementStatus[] = [
  "contradicted",
  "missing",
  "partial",
  "addressed",
]

export function RequirementsPanel({
  requirements,
  counters,
}: {
  requirements: Requirement[]
  counters?: Record<string, number>
}) {
  const [filter, setFilter] = useState<RequirementStatus | "all">("all")

  const counts = STATUS_ORDER.map((status) => ({
    status,
    n: counters?.[({addressed: "satisfied", partial: "partial_or_unclear", missing: "not_found", contradicted: "contradicted"})[status]] ?? requirements.filter((r) => r.status === status).length,
  }))

  const shown =
    filter === "all"
      ? requirements
      : requirements.filter((r) => r.status === filter)

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={cn(
            "editorial cursor-pointer transition-colors",
            filter === "all"
              ? "text-ink underline underline-offset-4"
              : "text-ink-2 hover:text-ink",
          )}
        >
          All {requirements.length}
        </button>
        {counts.map(({ status, n }) => (
          <button
            key={status}
            type="button"
            disabled={n === 0}
            onClick={() => setFilter(status)}
            className={cn(
              "editorial cursor-pointer transition-colors disabled:cursor-default disabled:opacity-40",
              filter === status
                ? "text-ink underline underline-offset-4"
                : "text-ink-2 hover:text-ink",
            )}
          >
            {status} {n}
          </button>
        ))}
      </div>

      <ul className="border-rule border-t">
        {shown.map((req) => {
          const id = req.anchor_id ?? `e-req-${req.ref}`
          return (
            <li
              key={req.id}
              id={id}
              className="border-rule-hair grid scroll-mt-28 grid-cols-[2rem_1fr] gap-x-3 border-b py-3"
            >
              <Ref id={id} n={req.ref} />
              <div className="min-w-0">
                <Lemma
                  reading={req.status}
                  readingClassName={STATUS_STYLE[req.status]}
                  className="text-[0.98rem] leading-snug"
                >
                  {req.text}
                </Lemma>

                <p className="text-ink-2 mt-1.5 max-w-[68ch] text-[0.9rem] leading-relaxed">
                  {req.note}
                </p>
                {req.suggestedFix && <p className="mt-2 text-sm"><strong>Suggested action: </strong>{req.suggestedFix}</p>}

                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <CitationRef
                    citation={req.source}
                    sourceId={`req-${req.id}`}
                    also={[req.answeredAt]}
                  />
                  {req.answeredAt ? (
                    <CitationRef
                      citation={req.answeredAt}
                      sourceId={`req-${req.id}`}
                      also={[req.source]}
                    />
                  ) : (
                    <span className="text-ink-2 font-sans text-[0.8rem] italic">
                      no answering passage
                    </span>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/* ----------------------------------------------------------------- issues -- */

export type IssueVerdict = "open" | "fixed" | "not-relevant"

function CopyFix({ text }: { text: string }) {
  const [done, setDone] = useState(false)

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          toast.success("Suggested fix copied")
          window.setTimeout(() => setDone(false), 1600)
        } catch {
          toast.error(
            "Could not reach the clipboard. Select the text to copy it.",
          )
        }
      }}
      className={cn(
        "editorial border-rule text-ink-2 inline-flex shrink-0 cursor-pointer items-center gap-1.5 border px-2 py-1.5",
        "hover:border-ink hover:text-ink transition-colors",
      )}
    >
      {done ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {done ? "Copied" : "Copy"}
    </button>
  )
}

function IssueEntry({
  issue,
  criterionName,
  showSeverity,
  verdict,
  onVerdict,
  applied,
  onApply,
  onRevert,
  defaultOpen,
}: {
  issue: Issue
  criterionName: string
  /** Only where the group does not already state it — i.e. the settled list. */
  showSeverity: boolean
  verdict: IssueVerdict
  onVerdict: (next: IssueVerdict) => void
  applied: boolean
  onApply: () => void
  onRevert: () => void
  defaultOpen: boolean
}) {
  const id = `e-iss-${issue.ref}`
  const [open, setOpen] = useState(() => defaultOpen || targeted(id))
  const { collate, pending, preview } = useCollation()
  const settled = verdict !== "open"
  const previewing = pending?.issueId === issue.id

  return (
    <li
      id={id}
      className="border-rule-hair grid scroll-mt-28 grid-cols-[2rem_1fr] gap-x-3 border-b py-3"
    >
      <Ref id={id} n={issue.ref} />

      <div className="min-w-0">
        <button
          type="button"
          onClick={() => {
            setOpen((v) => !v)
            collate(`iss-${issue.id}`, [issue.location, issue.against])
          }}
          className="w-full cursor-pointer text-left"
          aria-expanded={open}
        >
          <Lemma
            reading={
              showSeverity
                ? `${SEVERITY_LABEL[issue.severity]} · ${criterionName}`
                : criterionName
            }
            readingClassName={
              showSeverity ? SEVERITY_STYLE[issue.severity] : "text-ink-2"
            }
            className={cn(
              "text-[1rem] leading-snug",
              settled && "text-ink-2 [&>span:first-child]:line-through",
            )}
          >
            {issue.lemma}
          </Lemma>
          <ChevronDown
            aria-hidden
            className={cn(
              "text-ink-2 ml-1.5 inline size-3.5 shrink-0 align-middle transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </button>

        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
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
          {applied && (
            <span className="editorial text-ink">applied to the draft</span>
          )}
        </div>

        {open && (
          <div className="mt-3">
            {issue.quoted && (
              <blockquote className="border-rule text-ink-2 max-w-[66ch] border-l pl-3 font-serif text-[0.95rem] leading-relaxed italic">
                {issue.quoted}
              </blockquote>
            )}

            <p className="text-ink mt-2.5 max-w-[68ch] text-[0.95rem] leading-relaxed">
              {issue.whyItMatters}
            </p>

            <div className="border-rule bg-paper-inset mt-3 border">
              <div className="border-rule-hair flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b px-3 py-1.5">
                <span className="editorial text-ink-2">{issue.fixKind === "action" ? "Suggested action — human confirmation required" : "Suggested fix"}</span>
                <CopyFix text={issue.suggestedFix} />
              </div>
              <p className="text-ink px-3 py-2.5 font-serif text-[0.97rem] leading-relaxed whitespace-pre-wrap">
                {issue.suggestedFix}
              </p>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
              {/* These two change the draft. */}
              <span className="flex items-center gap-x-4 whitespace-nowrap">
              {!applied && issue.fixKind !== "action" && (
                <button
                  type="button"
                  onClick={() => {
                    if (previewing) {
                      preview(null)
                      return
                    }
                    collate(`iss-${issue.id}`, [issue.location, issue.against])
                    preview({
                      issueId: issue.id,
                      at: issue.location,
                      text: issue.suggestedFix,
                    })
                  }}
                  className={cn(
                    "editorial inline-flex cursor-pointer items-center gap-1.5 transition-colors",
                    previewing ? "text-ink" : "text-ink-2 hover:text-ink",
                  )}
                >
                  <Eye className="size-3.5" />
                  {previewing ? "Hide preview" : "Preview in draft"}
                </button>
              )}

              {issue.fixKind !== "action" && (applied ? (
                <button
                  type="button"
                  onClick={() => {
                    preview(null)
                    onRevert()
                  }}
                  className="editorial text-ink-2 hover:text-ink inline-flex cursor-pointer items-center gap-1.5 transition-colors"
                >
                  <Undo2 className="size-3.5" />
                  Revert
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    preview(null)
                    onApply()
                  }}
                  className="editorial text-ink-2 hover:text-ink inline-flex cursor-pointer items-center gap-1.5 transition-colors"
                >
                  <FilePlus2 className="size-3.5" />
                  Apply to draft
                </button>
              ))}

              </span>

              <span
                aria-hidden
                className="bg-rule hidden h-3.5 w-px shrink-0 sm:block"
              />

              {/* These two change only your own triage, not the draft. */}
              <span className="flex items-center gap-x-4 whitespace-nowrap">
              <button
                type="button"
                onClick={() => onVerdict(verdict === "fixed" ? "open" : "fixed")}
                className={cn(
                  "editorial inline-flex cursor-pointer items-center gap-1.5 transition-colors",
                  verdict === "fixed" ? "text-ink" : "text-ink-2 hover:text-ink",
                )}
              >
                <Check className="size-3.5" />
                {verdict === "fixed" ? "Marked fixed" : "Mark fixed"}
              </button>
              <button
                type="button"
                onClick={() =>
                  onVerdict(verdict === "not-relevant" ? "open" : "not-relevant")
                }
                className={cn(
                  "editorial inline-flex cursor-pointer items-center gap-1.5 transition-colors",
                  verdict === "not-relevant"
                    ? "text-ink"
                    : "text-ink-2 hover:text-ink",
                )}
              >
                <Minus className="size-3.5" />
                {verdict === "not-relevant" ? "Marked aside" : "Not relevant"}
              </button>
              </span>
            </div>
          </div>
        )}
      </div>
    </li>
  )
}

export function IssuesPanel({
  issues,
  criteria,
  verdicts,
  onVerdict,
  appliedFixes,
  onApply,
  onRevert,
}: {
  issues: Issue[]
  criteria: Criterion[]
  verdicts: Record<string, IssueVerdict>
  onVerdict: (id: string, next: IssueVerdict) => void
  appliedFixes: Record<string, boolean>
  onApply: (issue: Issue) => void
  onRevert: (issue: Issue) => void
}) {
  const order: Severity[] = ["must", "should", "optional"]
  const names = new Map(criteria.map((c) => [c.id, c.name]))
  const open = issues.filter((i) => (verdicts[i.id] ?? "open") === "open")
  const settled = issues.filter((i) => (verdicts[i.id] ?? "open") !== "open")

  const entry = (issue: Issue, defaultOpen: boolean, showSeverity = false) => (
    <IssueEntry
      key={issue.id}
      issue={issue}
      criterionName={names.get(issue.criterionId) ?? "Uncategorised"}
      showSeverity={showSeverity}
      verdict={verdicts[issue.id] ?? "open"}
      onVerdict={(next) => onVerdict(issue.id, next)}
      applied={appliedFixes[issue.id] ?? false}
      onApply={() => onApply(issue)}
      onRevert={() => onRevert(issue)}
      defaultOpen={defaultOpen}
    />
  )

  return (
    <div>
      {order.map((severity) => {
        const group = open.filter((i) => i.severity === severity)
        if (group.length === 0) return null

        return (
          <section key={severity} className="mb-5">
            <h3 className="editorial text-ink-2 border-rule mb-0 border-b pb-1.5">
              {SEVERITY_LABEL[severity]} · {group.length}
            </h3>
            <ul>{group.map((i, n) => entry(i, severity === "must" && n === 0))}</ul>
          </section>
        )
      })}

      {settled.length > 0 && (
        <section>
          <h3 className="editorial text-ink-2 border-rule mb-0 border-b pb-1.5">
            Settled · {settled.length}
          </h3>
          <ul>{settled.map((i) => entry(i, false, true))}</ul>
        </section>
      )}

      {open.length === 0 && issues.length > 0 && (
        <p className="text-ink-2 border-rule border-t py-8 text-center text-[0.9rem]">
          Every issue is settled. Re-run the review against the edited draft to
          confirm the score moved.
        </p>
      )}
    </div>
  )
}
