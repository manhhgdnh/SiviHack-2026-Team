import { useState } from "react"
import { ArrowRight, ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Criterion, WeightSuggestion } from "@/api/schema"
import { SAMPLES, type SampleId } from "@/api/fixtures/documents"

import { CriteriaSetup, type SuggestState } from "./criteria-setup"
import { WitnessInput } from "./witness-input"

export function SetupView({
  rfp,
  proposal,
  onRfp,
  onProposal,
  criteria,
  onCriteria,
  onSuggest,
  suggestions,
  suggestState,
  suggestError,
  extracted,
  onRun,
  onSample,
  activeSample,
  error,
}: {
  rfp: string
  proposal: string
  onRfp: (v: string) => void
  onProposal: (v: string) => void
  criteria: Criterion[]
  onCriteria: (next: Criterion[]) => void
  onSuggest: () => void
  suggestions: WeightSuggestion[] | null
  suggestState: SuggestState
  suggestError: string | null
  extracted: { requirements: number; constraints: number } | null
  onRun: () => void
  onSample: (id: SampleId) => void
  activeSample: SampleId | null
  error: string | null
}) {
  const [openCriteria, setOpenCriteria] = useState(true)
  const rfpEmpty = rfp.trim().length === 0
  // The proposal is the only required witness: the backend scores without an RFP.
  const ready = proposal.trim().length > 0
  const enabled = criteria.filter((c) => c.enabled).length

  return (
    <div className="flex min-h-svh flex-col">
      <header className="bg-ink text-cloth-text">
        <div className="mx-auto flex max-w-[112rem] flex-col gap-4 px-5 py-5 sm:px-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-[64ch]">
            <h1
              className="hand-condensed text-[1.6rem] leading-[0.92] font-semibold uppercase sm:text-[2rem]"
              style={{ letterSpacing: "-0.035em" }}
            >
              Proposal Scorer
            </h1>
            <p className="text-cloth-text/75 mt-1.5 text-[0.9rem] leading-relaxed">
              Reads your draft against the client&rsquo;s RFP and shows where it
              falls short — with the passage behind every judgment, so you can
              check the call rather than trust it.
            </p>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-2">
            <button
              type="button"
              onClick={onRun}
              disabled={!ready}
              className={cn(
                "editorial bg-cloth-text text-ink inline-flex cursor-pointer items-center gap-2 px-5 py-3",
                "transition-opacity hover:opacity-85",
                "disabled:cursor-not-allowed disabled:bg-cloth-text/45 disabled:text-ink/70",
              )}
            >
              Run review
              <ArrowRight className="size-3.5" />
            </button>
            {ready && rfpEmpty && (
              <p role="status" className="text-cloth-text/75 text-[0.78rem]">
                No RFP loaded — the draft will be scored on its own.
              </p>
            )}
          </div>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          aria-label="Review failed"
          className="border-cloth-stop bg-cloth-stop/8 border-b"
        >
          <div className="mx-auto max-w-[112rem] px-5 py-3 sm:px-8">
            <p className="text-cloth-stop text-[0.85rem] font-semibold">{error}</p>
          </div>
        </div>
      )}

      <main className="mx-auto flex w-full max-w-[112rem] flex-1 flex-col gap-6 px-5 py-6 sm:px-8">
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 py-1">
          <span className="editorial text-ink-2 mr-1.5">Load a sample</span>
          {(Object.keys(SAMPLES) as SampleId[]).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => onSample(id)}
              aria-pressed={activeSample === id}
              className={cn(
                "editorial cursor-pointer border px-2.5 py-1.5 transition-colors",
                activeSample === id
                  ? "border-ink bg-ink text-paper"
                  : "border-rule text-ink-2 hover:border-ink hover:text-ink",
              )}
            >
              {SAMPLES[id].label}
            </button>
          ))}
        </div>

        <div className="grid min-h-[26rem] flex-1 gap-5 lg:grid-cols-2">
          <WitnessInput
            of="R"
            title="Request for Proposal"
            role="The client's brief — the authority the draft is measured against"
            placeholder="Paste the client's RFP or brief here, or upload the .md file."
            value={rfp}
            onChange={onRfp}
            optional
          />
          <WitnessInput
            of="P"
            title="Draft Proposal"
            role="The text under review — your response, as it stands"
            placeholder="Paste the draft proposal here, or upload the .md file."
            value={proposal}
            onChange={onProposal}
          />
        </div>

        <section className="border-rule border">
          <button
            type="button"
            onClick={() => setOpenCriteria((v) => !v)}
            aria-expanded={openCriteria}
            className="hover:bg-paper-inset flex w-full cursor-pointer items-center justify-between gap-4 px-4 py-3 text-left transition-colors"
          >
            <span className="min-w-0">
              <span className="text-ink block text-[0.9rem] font-semibold">
                Criteria and weights
              </span>
              <span className="text-ink-2 block text-[0.78rem]">
                {enabled} criteria, sharing 100 points. Optional — the defaults
                score every proposal the same way.
              </span>
            </span>
            <ChevronDown
              className={cn(
                "text-ink-2 size-4 shrink-0 transition-transform duration-200",
                openCriteria && "rotate-180",
              )}
            />
          </button>

          {openCriteria && (
            <div className="border-rule-hair border-t px-4 py-5">
              <CriteriaSetup
                criteria={criteria}
                onChange={onCriteria}
                onSuggest={onSuggest}
                suggestions={suggestions}
                suggestState={suggestState}
                suggestError={suggestError}
                extracted={extracted}
                rfpEmpty={rfpEmpty}
              />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
