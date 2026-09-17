import { useState } from "react"
import { Check, ChevronDown, Copy, Eye, FilePlus2, Minus, Undo2 } from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import type {
  Constraint,
  ConstraintKind,
  Criterion,
  CriterionScore,
  FindingType,
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
   Severity is set in type, not in colour. Position, weight and case carry the
   four states; the editor's crimson is spent on the draft going against the RFP.
-------------------------------------------------------------------------- */

/**
 * A requirement's status borrows the binding's colours, so the four states
 * read at a glance: green addressed, ochre partial, crimson contradicted,
 * ink for not found. Severity (must / should / optional) stays typographic.
 */
export const STATUS_STYLE: Record<RequirementStatus, string> = {
  addressed: "text-cloth-ready font-semibold",
  partial: "text-cloth-fix font-semibold",
  missing: "text-ink font-bold",
  contradicted: "text-cloth-stop font-bold",
}

export const STATUS_SWATCH: Record<RequirementStatus, string> = {
  addressed: "bg-cloth-ready",
  partial: "bg-cloth-fix",
  missing: "bg-ink",
  contradicted: "bg-cloth-stop",
}

export const STATUS_LABEL: Record<RequirementStatus, string> = {
  addressed: "addressed",
  partial: "partial / unclear",
  missing: "not found",
  contradicted: "contradicted",
}

const STATUS_SHORT: Record<RequirementStatus, string> = {
  addressed: "Addressed",
  partial: "Partial",
  missing: "Not found",
  contradicted: "Contradicted",
}

export const CONSTRAINT_LABEL: Record<ConstraintKind, string> = {
  BUDGET: "Budget",
  DEADLINE: "Deadline",
  TECHNOLOGY: "Technology",
  SCOPE: "Scope",
  LEGAL: "Legal",
  OTHER: "Other",
}

export const FINDING_LABEL: Record<FindingType, string> = {
  OVERCOMMIT: "Overcommitment",
  SCOPE_CREEP: "Scope creep",
  UNREALISTIC_TIMELINE: "Unrealistic timeline",
  PRICING_MISMATCH: "Pricing mismatch",
  VAGUENESS: "Vague wording",
  INCONSISTENCY: "Inconsistency",
}

/** Why the requirements list is empty, when it is. */
export type EmptyReason = "no-rfp" | "nothing-extracted" | null

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/**
 * The sign: a requirement's status as colour alone, at the right of its row.
 * The tally above the list is its legend; the name travels in the title and
 * for screen readers. A hollow square is a verdict that was never reached
 * (unassessed) or a constraint the draft respected.
 */
export function StatusSign({
  status,
  title,
}: {
  status: RequirementStatus | "unassessed" | "respected"
  title?: string
}) {
  const hollow = status === "unassessed" || status === "respected"
  const label = hollow ? (status === "unassessed" ? "not assessed" : "respected") : STATUS_LABEL[status]
  return (
    <span
      role="img"
      aria-label={label}
      title={title ?? capital(label)}
      className={cn(
        "mt-[0.3rem] block size-3.5 shrink-0",
        hollow ? "border-rule bg-paper border" : STATUS_SWATCH[status],
      )}
    />
  )
}

/** A square of the status colour, set beside the word. */
export function StatusSwatch({
  status,
  className,
}: {
  status: RequirementStatus
  className?: string
}) {
  return (
    <span aria-hidden className={cn("inline-block size-2 shrink-0", STATUS_SWATCH[status], className)} />
  )
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

/** Severity borrows the binding's ramp, but only at the group head and the entry's square. */
const SEVERITY_HEAD: Record<Severity, string> = {
  must: "text-cloth-stop",
  should: "text-cloth-fix",
  optional: "text-ink-3",
}

const SEVERITY_SWATCH: Record<Severity, string> = {
  must: "bg-cloth-stop",
  should: "bg-cloth-fix",
  optional: "bg-ink-3",
}

/** A group head: the level in its colour over a solid rule, the count beside it. */
function GroupHead({
  label,
  count,
  className,
  swatch,
}: {
  label: string
  count: number
  className: string
  swatch?: string
}) {
  return (
    <h3
      className={cn(
        "hand-condensed border-ink flex items-center gap-2.5 border-b pb-1.5 text-[1.35rem] leading-none font-semibold tracking-tight uppercase",
        className,
      )}
    >
      {swatch && <span aria-hidden className={cn("inline-block size-2.5 shrink-0", swatch)} />}
      {label}
      <span data-numeric className="text-ink-2 font-sans text-[0.8rem] font-semibold tracking-normal normal-case">
        {count}
      </span>
    </h3>
  )
}

const targeted = (id: string) => typeof location !== "undefined" && location.hash === `#${id}`

/* -------------------------------------------------------------- criteria -- */

function ScoreMarks({ score }: { score: number | null }) {
  return (
    <span
      className="flex shrink-0 items-center gap-[3px]"
      aria-label={score === null ? "not assessed" : `${score} out of 5`}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={cn("h-3.5 w-[3px]", score !== null && n <= score ? "bg-ink" : "bg-rule")} />
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
  const byId = new Map(scores.map((s) => [s.criterionId, s]))

  return (
    <ul className="border-rule border-t">
      {criteria
        .filter((c) => c.enabled)
        .map((c) => {
          const s = byId.get(c.id) ?? null
          const score = s?.score ?? null
          const rawNote = s ? s.note : "No score returned."
          const note = rawNote
            ? capital(rawNote) + (score === null && !rawNote.endsWith(".") ? "." : "") + (score === null ? " Not counted in the overall." : "")
            : null

          return (
            <li key={c.id} id={`e-crit-${c.id}`} className="border-rule-hair scroll-mt-28 border-b py-3.5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1.5">
                  <Lemma
                    reading={score === null ? "—" : `${score}/5`}
                    readingClassName="text-ink font-bold"
                    className="text-[1rem] leading-snug font-semibold"
                  >
                    {c.name}
                  </Lemma>
                  <div className="flex items-center gap-2.5">
                    <ScoreMarks score={score} />
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
                      onValueChange={([next]) => onCriteria(redistribute(criteria, c.id, next))}
                      className="max-w-[16rem] min-w-0 flex-1"
                    />
                    <span className="editorial text-ink-3">share of 100</span>
                  </div>
                )}

                {note && (
                  <p className="text-ink-3 mt-2 max-w-[68ch] text-[0.78rem] leading-relaxed italic">{note}</p>
                )}
                {s?.strength && (
                  <p className="text-ink-2 mt-2 max-w-[68ch] text-[0.9rem] leading-relaxed">{s.strength}</p>
                )}
                {s?.weakness && (
                  <p className="text-ink mt-1 max-w-[68ch] text-[0.95rem] leading-relaxed">{s.weakness}</p>
                )}

                {s && s.citations.length > 0 && (
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
                )}
              </div>
            </li>
          )
        })}
    </ul>
  )
}

/* ---------------------------------------------------------- requirements -- */

const STATUS_ORDER: RequirementStatus[] = ["contradicted", "missing", "partial", "addressed"]

export function RequirementsPanel({
  requirements,
  constraints,
  issues,
  unassessed,
  emptyReason,
}: {
  requirements: Requirement[]
  constraints: Constraint[]
  issues: Issue[]
  /** The analysis call failed: the requirements are real, their statuses are not. */
  unassessed: boolean
  emptyReason: EmptyReason
}) {
  const [filter, setFilter] = useState<RequirementStatus | "all">("all")

  if (requirements.length === 0) {
    return (
      <p className="text-ink-2 border-rule border-t py-8 text-center text-[0.9rem]">
        {emptyReason === "nothing-extracted"
          ? "Nothing could be extracted from the RFP. Edit it and re-run to see coverage."
          : "No client requirements to check against — no RFP was provided. Add the RFP and re-run to see coverage."}
      </p>
    )
  }

  const counts = STATUS_ORDER.map((status) => ({
    status,
    n: requirements.filter((r) => r.status === status).length,
  }))

  const shown =
    unassessed || filter === "all" ? requirements : requirements.filter((r) => r.status === filter)

  const violated = (c: Constraint) => issues.some((i) => i.id === `vio-${c.id}`)

  return (
    <div>
      {unassessed ? (
        <p className="text-ink-2 mb-4 text-[0.9rem]">
          Coverage was not assessed — the analysis call failed. Re-run to check the draft against
          these requirements.
        </p>
      ) : (
        /*
          The tally: one strip of cells, a count over its name, each a filter.
          The numeral carries the status colour, so the strip is its own legend.
        */
        <div className="mb-4 flex flex-wrap" role="group" aria-label="Requirements by status">
          <button
            type="button"
            onClick={() => setFilter("all")}
            aria-pressed={filter === "all"}
            className={cn(
              "relative flex cursor-pointer flex-col items-start gap-1 px-3 py-2.5 text-left transition-colors",
              filter === "all" ? "text-ink" : "text-ink-2 hover:text-ink",
            )}
          >
            <span data-numeric className="font-sans text-[1.5rem] leading-none font-semibold tabular-nums">
              {requirements.length}
            </span>
            <span className="editorial whitespace-nowrap">Asked</span>
            {filter === "all" && (
              <span aria-hidden className="bg-ink absolute inset-x-0 -bottom-px h-[2px]" />
            )}
          </button>
          {counts.map(({ status, n }) => (
            <button
              key={status}
              type="button"
              disabled={n === 0}
              onClick={() => setFilter(filter === status ? "all" : status)}
              aria-pressed={filter === status}
              className={cn(
                "relative flex cursor-pointer flex-col items-start gap-1 px-3 py-2.5 text-left transition-opacity",
                "disabled:cursor-default disabled:opacity-35",
                n === 0 ? "text-ink-3" : STATUS_STYLE[status],
                filter !== "all" && filter !== status && "opacity-55 hover:opacity-100",
              )}
            >
              <span data-numeric className="font-sans text-[1.5rem] leading-none font-semibold tabular-nums">
                {n}
              </span>
              <span className="editorial whitespace-nowrap">{STATUS_SHORT[status]}</span>
              {filter === status && (
                <span aria-hidden className="bg-ink absolute inset-x-0 -bottom-px h-[2px]" />
              )}
            </button>
          ))}
        </div>
      )}

      <ul className="border-rule border-t">
        {shown.map((req) => (
          <li
            key={req.id}
            id={`e-req-${req.id}`}
            className="border-rule-hair grid scroll-mt-28 grid-cols-[1fr_auto] gap-x-3 border-b py-3"
          >
            <div className="min-w-0">
              <p className="font-serif text-[0.98rem] leading-snug">{req.label}</p>
              {req.text && (
                <p className="text-ink-2 mt-1 max-w-[68ch] font-serif text-[0.92rem] leading-snug italic">
                  {req.text}
                </p>
              )}

              {!unassessed && req.note && (
                <p className="text-ink-2 mt-1.5 max-w-[68ch] text-[0.9rem] leading-relaxed">{req.note}</p>
              )}

              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <CitationRef
                  citation={req.source}
                  sourceId={`req-${req.id}`}
                  also={unassessed ? [] : [req.answeredAt]}
                  tone={unassessed ? null : req.status}
                />
                {!unassessed &&
                  (req.answeredAt ? (
                    <CitationRef
                      citation={req.answeredAt}
                      sourceId={`req-${req.id}`}
                      also={[req.source]}
                      tone={req.status}
                    />
                  ) : (
                    <span className="text-ink-2 font-sans text-[0.8rem] italic">no answering passage</span>
                  ))}
              </div>
            </div>
            <StatusSign status={unassessed ? "unassessed" : req.status} />
          </li>
        ))}
      </ul>

      {constraints.length > 0 && (
        <section className="mt-8">
          <GroupHead label="Constraints" count={constraints.length} className="text-ink" />
          <ul>
            {constraints.map((c) => (
              <li
                key={c.id}
                id={`e-con-${c.id}`}
                className="border-rule-hair grid scroll-mt-28 grid-cols-[1fr_auto] gap-x-3 border-b py-3"
              >
                <div className="min-w-0">
                  <Lemma
                    reading={CONSTRAINT_LABEL[c.kind]}
                    readingClassName="text-ink-2"
                    className="text-[0.98rem] leading-snug"
                  >
                    {c.label}
                  </Lemma>
                  {c.source.quote && (
                    <p className="text-ink-2 mt-1 max-w-[68ch] font-serif text-[0.92rem] leading-snug italic">
                      {c.source.quote}
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <CitationRef citation={c.source} sourceId={`con-${c.id}`} />
                  </div>
                </div>
                {unassessed ? (
                  <StatusSign status="unassessed" />
                ) : violated(c) ? (
                  <StatusSign status="contradicted" title="Violated" />
                ) : (
                  <StatusSign status="respected" />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
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
          toast.error("Could not reach the clipboard. Select the text to copy it.")
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

/** The reading beside the lemma: what kind of entry this is. */
function readingFor(issue: Issue, criterionName: string, showSeverity: boolean): string {
  const kind =
    issue.kind === "violation"
      ? `Constraint · ${CONSTRAINT_LABEL[issue.constraintKind]}`
      : issue.kind === "finding"
        ? `${criterionName} · ${FINDING_LABEL[issue.findingType]}`
        : criterionName
  return showSeverity ? `${SEVERITY_LABEL[issue.severity]} · ${kind}` : kind
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
  const id = `e-iss-${issue.id}`
  const [open, setOpen] = useState(() => defaultOpen || targeted(id))
  const { collate, pending, preview } = useCollation()
  const settled = verdict !== "open"
  const previewing = pending?.issueId === issue.id
  const violation = issue.kind === "violation"
  const fix = issue.suggestedFix

  return (
    <li id={id} className="border-rule-hair scroll-mt-28 border-b py-4">
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
          <span
            aria-hidden
            className={cn(
              "mr-2 inline-block size-2.5 shrink-0 translate-y-[-0.05em]",
              SEVERITY_SWATCH[issue.severity],
              settled && "opacity-40",
            )}
          />
          <Lemma
            reading={readingFor(issue, criterionName, showSeverity)}
            readingClassName={
              violation ? "text-ink font-bold" : showSeverity ? SEVERITY_STYLE[issue.severity] : "text-ink-2"
            }
            className={cn(
              "text-[1.05rem] leading-snug [&>span:first-child]:font-medium",
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
          {issue.location && (
            <CitationRef citation={issue.location} sourceId={`iss-${issue.id}`} also={[issue.against]} />
          )}
          {issue.against && (
            <CitationRef citation={issue.against} sourceId={`iss-${issue.id}`} also={[issue.location]} />
          )}
          {applied && <span className="editorial text-ink">applied to the draft</span>}
        </div>

        {violation && issue.against?.quote && (
          <p className="text-ink mt-1.5 text-[0.95rem] leading-snug">
            <Siglum />
            <span className="text-ink-2">asks</span>{" "}
            <span className="font-serif italic">“{issue.against.quote}”</span>
          </p>
        )}

        {open && (
          <div className="mt-3 @3xl:grid @3xl:grid-cols-2 @3xl:gap-x-8">
            <div className="min-w-0">
              {issue.quoted && (
                <>
                  <p className="editorial text-ink-3 mb-1.5">The draft says</p>
                  <blockquote className="border-rule text-ink-2 max-w-[66ch] border-l pl-3 font-serif text-[0.95rem] leading-relaxed italic">
                    {issue.quoted}
                  </blockquote>
                </>
              )}

              <p className="editorial text-ink-3 mt-3 mb-1.5 first:mt-0">
                {violation ? "Why it breaks the constraint" : "Why it matters"}
              </p>
              <p className="text-ink max-w-[68ch] text-[0.95rem] leading-relaxed">{issue.whyItMatters}</p>
            </div>

            <div className="min-w-0">
              {fix ? (
                <div className="border-rule bg-paper-inset mt-3 border @3xl:mt-0">
                  <div className="border-rule-hair flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b px-3 py-1.5">
                    <span className="editorial text-ink-2">Suggested fix</span>
                    <CopyFix text={fix} />
                  </div>
                  <p className="text-ink px-3 py-2.5 font-serif text-[0.97rem] leading-relaxed whitespace-pre-wrap">
                    {fix}
                  </p>
                </div>
              ) : (
                <p className="editorial text-ink-3 mt-3 @3xl:mt-0">No fix suggested</p>
              )}

              <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
                {/* These two change the draft. */}
                {fix && (
                  <span className="flex items-center gap-x-4 whitespace-nowrap">
                    {!applied && (
                      <button
                        type="button"
                        onClick={() => {
                          if (previewing) {
                            preview(null)
                            return
                          }
                          collate(`iss-${issue.id}`, [issue.location, issue.against])
                          preview({ issueId: issue.id, witness: "P", at: issue.location, text: fix })
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

                    {applied ? (
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
                    )}
                  </span>
                )}

                <span aria-hidden className="bg-rule hidden h-3.5 w-px shrink-0 sm:block" />

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
                    onClick={() => onVerdict(verdict === "not-relevant" ? "open" : "not-relevant")}
                    className={cn(
                      "editorial inline-flex cursor-pointer items-center gap-1.5 transition-colors",
                      verdict === "not-relevant" ? "text-ink" : "text-ink-2 hover:text-ink",
                    )}
                  >
                    <Minus className="size-3.5" />
                    {verdict === "not-relevant" ? "Marked aside" : "Not relevant"}
                  </button>
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </li>
  )
}

/** The R siglum inline, for the "asks" line. */
function Siglum() {
  return (
    <span
      aria-label="R"
      className="bg-witness-r text-cloth-text mr-1.5 inline-flex size-[1.15em] translate-y-[0.1em] items-center justify-center font-sans text-[0.65em] font-bold"
    >
      R
    </span>
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
  focus,
  unassessed,
}: {
  issues: Issue[]
  criteria: Criterion[]
  verdicts: Record<string, IssueVerdict>
  onVerdict: (id: string, next: IssueVerdict) => void
  appliedFixes: Record<string, boolean>
  onApply: (issue: Issue) => void
  onRevert: (issue: Issue) => void
  /** An entry to open on arrival; `n` changes on every request so a repeat still opens it. */
  focus?: { id: string; n: number } | null
  /** The analysis call failed, so there were no issues to find. */
  unassessed?: boolean
}) {
  const order: Severity[] = ["must", "should", "optional"]
  const names = new Map(criteria.map((c) => [c.id, c.name]))
  const open = issues.filter((i) => (verdicts[i.id] ?? "open") === "open")
  const settled = issues.filter((i) => (verdicts[i.id] ?? "open") !== "open")

  if (unassessed) {
    return (
      <p className="text-ink-2 border-rule border-t py-8 text-center text-[0.9rem]">
        No issues were assessed.
      </p>
    )
  }

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
      defaultOpen={defaultOpen || focus?.id === issue.id}
    />
  )

  const violations = open.filter((i) => i.kind === "violation")
  const groups = order.map((severity) => ({
    severity,
    group: open.filter((i) => i.kind !== "violation" && i.severity === severity),
  }))
  // The first entry of the first non-empty group opens by default, so a violation is never
  // folded away above the fold.
  const firstId = (violations[0] ?? groups.flatMap((g) => g.group)[0])?.id ?? null

  return (
    // Keyed on the focus request so a "show me" remounts the list with that entry open.
    <div key={focus?.n ?? 0}>
      {violations.length > 0 && (
        <section className="mb-8">
          <GroupHead
            label="Violates a client constraint"
            count={violations.length}
            className="text-cloth-stop"
            swatch="bg-cloth-stop"
          />
          <ul>{violations.map((i) => entry(i, i.id === firstId))}</ul>
        </section>
      )}

      {groups.map(({ severity, group }) => {
        if (group.length === 0) return null
        return (
          <section key={severity} className="mb-8">
            <GroupHead
              label={SEVERITY_LABEL[severity]}
              count={group.length}
              className={SEVERITY_HEAD[severity]}
              swatch={SEVERITY_SWATCH[severity]}
            />
            <ul>{group.map((i) => entry(i, i.id === firstId))}</ul>
          </section>
        )
      })}

      {settled.length > 0 && (
        <section>
          <GroupHead label="Settled" count={settled.length} className="text-ink-3" />
          <ul>{settled.map((i) => entry(i, false, true))}</ul>
        </section>
      )}

      {open.length === 0 && issues.length > 0 && (
        <p className="text-ink-2 border-rule border-t py-8 text-center text-[0.9rem]">
          Every issue is settled. Re-run the review against the edited draft to confirm the score moved.
        </p>
      )}

      {issues.length === 0 && (
        <p className="text-ink-2 border-rule border-t py-8 text-center text-[0.9rem]">
          No issues found: every requirement is addressed and nothing was flagged.
        </p>
      )}
    </div>
  )
}
