import { useMemo, useState } from "react"
import { useMutation } from "@tanstack/react-query"

import type { Criterion, Issue, Witness } from "@/api/schema"
import { ReviewError, runReview, suggestWeights } from "@/api/client"
import { RFP_TEXT, SAMPLES, type SampleId } from "@/api/fixtures/documents"
import { BASE_CRITERIA } from "@/api/fixtures/reviews"
import { rebalance } from "@/lib/score"
import { CollationProvider } from "@/components/apparatus/collation"

import type { IssueVerdict } from "@/features/review/apparatus"
import { ReviewView } from "@/features/review/review-view"
import { RunTrace } from "@/features/review/run-trace"
import { SetupView } from "@/features/review/setup-view"

export default function App() {
  const [rfp, setRfp] = useState("")
  const [proposal, setProposal] = useState("")
  const [criteria, setCriteria] = useState<Criterion[]>(BASE_CRITERIA)
  const [step, setStep] = useState(0)
  const [issueVerdicts, setIssueVerdicts] = useState<Record<string, IssueVerdict>>({})
  const [editing, setEditing] = useState(false)
  const [activeSample, setActiveSample] = useState<SampleId | null>(null)
  const [appliedFixes, setAppliedFixes] = useState<Record<string, boolean>>({})
  /** The draft the current review was computed against, for staleness. */
  const [reviewedAgainst, setReviewedAgainst] = useState("")

  const review = useMutation({
    mutationFn: (input: { rfp: string; proposal: string; criteria: Criterion[] }) =>
      runReview(input, { onStep: setStep }),
    onMutate: () => {
      setStep(0)
      setEditing(false)
    },
    onSuccess: (_data, input) => {
      setIssueVerdicts({})
      setAppliedFixes({})
      setReviewedAgainst(input.proposal)
    },
  })

  const weights = useMutation({
    mutationFn: (source: string) => suggestWeights(source),
    onSuccess: (suggestions) => {
      setCriteria((current) =>
        rebalance(
          current.map((c) => {
            const found = suggestions.find((s) => s.criterionId === c.id)
            return found ? { ...c, weight: found.weight } : c
          }),
        ),
      )
    },
  })

  const witnesses = useMemo<{ R: Witness; P: Witness }>(
    () => ({
      R: {
        siglum: "R",
        title: "Request for Proposal",
        subtitle: "The client's brief",
        lines: rfp.split("\n"),
      },
      P: {
        siglum: "P",
        title: "Draft Proposal",
        subtitle: "The text under review",
        lines: proposal.split("\n"),
      },
    }),
    [rfp, proposal],
  )

  /**
   * A fix is applied as a block after the passage it answers, so the draft can
   * be re-run and the score watched to move. Reverting removes that exact
   * block, which is why it is matched on its own text rather than an index
   * that a later apply would have shifted.
   */
  const applyFix = (issue: Issue) => {
    if (issue.fixKind === "action") return
    const lines = proposal.split("\n")
    const at = Math.min(issue.location.to, lines.length)
    setProposal(
      [...lines.slice(0, at), "", issue.suggestedFix, ...lines.slice(at)].join(
        "\n",
      ),
    )
    setAppliedFixes((current) => ({ ...current, [issue.id]: true }))
  }

  const revertFix = (issue: Issue) => {
    setProposal((current) => current.replace(`\n\n${issue.suggestedFix}`, ""))
    setAppliedFixes((current) => {
      const next = { ...current }
      delete next[issue.id]
      return next
    })
  }

  const score = review.data?.overall ?? 0
  const verdict = review.data?.verdict ?? "not-ready"

  const errorMessage =
    review.error instanceof ReviewError
      ? review.error.message
      : review.error
        ? "The review could not be completed. Check both documents and try again."
        : null

  const run = () => review.mutate({ rfp, proposal, criteria })

  // Loading. The trace shows which step is running, never a blank panel.
  if (review.isPending) {
    return <RunTrace active={step} />
  }

  // Success.
  if (review.data && !editing && !review.error) {
    return (
      <CollationProvider>
        <ReviewView
          review={review.data}
          criteria={criteria}
          witnesses={witnesses}
          score={score}
          verdict={verdict}
          verdicts={issueVerdicts}
          onVerdict={(id, next) =>
            setIssueVerdicts((current) => ({ ...current, [id]: next }))
          }
          onEdit={() => setEditing(true)}
          onRerun={run}
          rerunning={review.isPending}
          stale={proposal !== reviewedAgainst}
          appliedFixes={appliedFixes}
          onApply={applyFix}
          onRevert={revertFix}
        />
      </CollationProvider>
    )
  }

  // Empty, and error — the same view, which is also where recovery happens.
  return (
    <SetupView
      rfp={rfp}
      proposal={proposal}
      onRfp={(v) => {
        setRfp(v)
        setActiveSample(null)
      }}
      onProposal={(v) => {
        setProposal(v)
        setActiveSample(null)
      }}
      criteria={criteria}
      onCriteria={setCriteria}
      onSuggest={() => weights.mutate(rfp || RFP_TEXT)}
      suggestions={weights.data ?? null}
      suggesting={weights.isPending}
      onRun={run}
      onSample={(id) => {
        setRfp(RFP_TEXT)
        setProposal(SAMPLES[id].text)
        setActiveSample(id)
      }}
      activeSample={activeSample}
      error={errorMessage}
    />
  )
}
