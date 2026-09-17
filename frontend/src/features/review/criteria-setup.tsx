import { useState } from "react"
import { Loader2, Plus, X } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Criterion, WeightSuggestion } from "@/api/schema"
import { rebalance, redistribute } from "@/lib/score"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"

/**
 * Weights are shares of a fixed 100 and they compete. Raising one takes from
 * the others on screen, so the budget is visible rather than implied.
 */
function BudgetRule({ criteria }: { criteria: Criterion[] }) {
  const enabled = criteria.filter((c) => c.enabled)

  return (
    <div className="mb-5">
      <div
        className="border-rule bg-paper-inset flex h-9 w-full border"
        role="img"
        aria-label={`Weight budget: ${enabled
          .map((c) => `${c.name} ${c.weight} per cent`)
          .join(", ")}`}
      >
        {enabled.map((c, i) => (
          <div
            key={c.id}
            style={{ width: `${c.weight}%` }}
            title={`${c.name} — ${c.weight}%`}
            className={cn(
              "relative grid min-w-0 place-items-center overflow-hidden transition-[width] duration-200 ease-out",
              i % 2 === 0 ? "bg-ink" : "bg-ink-2",
            )}
          >
            <span
              data-numeric
              className="text-cloth-text font-sans text-[0.65rem] font-semibold tabular-nums"
            >
              {c.weight >= 7 ? c.weight : ""}
            </span>
          </div>
        ))}
      </div>
      <div className="text-ink-3 mt-1.5 flex justify-between font-sans text-[0.65rem]">
        <span>0</span>
        <span data-numeric>
          {enabled.length} of {criteria.length} criteria · 100 shared
        </span>
        <span>100</span>
      </div>
    </div>
  )
}

export function CriteriaSetup({
  criteria,
  onChange,
  onSuggest,
  suggestions,
  suggesting,
  disabled,
}: {
  criteria: Criterion[]
  onChange: (next: Criterion[]) => void
  onSuggest: () => void
  suggestions: WeightSuggestion[] | null
  suggesting: boolean
  disabled?: boolean
}) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ name: "", whatToCheck: "" })

  const reasonFor = (id: string) =>
    suggestions?.find((s) => s.criterionId === id)?.reason ?? null

  const addCustom = () => {
    if (!draft.name.trim()) return
    const next = rebalance([
      ...criteria,
      {
        id: `c-custom-${Date.now()}`,
        name: draft.name.trim(),
        whatToCheck:
          draft.whatToCheck.trim() || "No check described for this criterion.",
        enabled: true,
        weight: Math.round(100 / (criteria.filter((c) => c.enabled).length + 1)),
        custom: true,
      },
    ])
    onChange(next)
    setDraft({ name: "", whatToCheck: "" })
    setAdding(false)
  }

  return (
    <div>
      <BudgetRule criteria={criteria} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onSuggest}
          disabled={disabled || suggesting}
          className={cn(
            "editorial border-ink text-ink inline-flex items-center gap-2 border px-3 py-2",
            "hover:bg-ink hover:text-paper cursor-pointer transition-colors",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {suggesting && <Loader2 className="size-3.5 animate-spin" />}
          Reset to equal weights
        </button>
        {suggestions && (
          <p className="text-ink-2 max-w-prose text-[0.78rem]">
            Application defaults, not inferred client priorities. Adjust weights before reviewing.
          </p>
        )}
      </div>

      <ul className="border-rule border-t">
        {criteria.map((c, i) => {
          const reason = reasonFor(c.id)
          return (
            <li
              key={c.id}
              className={cn(
                "border-rule-hair grid grid-cols-[2.25rem_1fr] gap-x-2 border-b py-3.5 sm:grid-cols-[2.25rem_1fr_13rem]",
                !c.enabled && "opacity-45",
              )}
            >
              <span
                data-numeric
                className="text-ink-3 pt-0.5 text-right font-sans text-[0.7rem] tabular-nums"
              >
                {i + 1}
              </span>

              <div className="min-w-0">
                <div className="flex items-start gap-2.5">
                  <Switch
                    checked={c.enabled}
                    disabled={disabled}
                    aria-label={`Include ${c.name}`}
                    onCheckedChange={(on) =>
                      onChange(
                        rebalance(
                          criteria.map((x) =>
                            x.id === c.id ? { ...x, enabled: on } : x,
                          ),
                        ),
                      )
                    }
                    className="mt-0.5 shrink-0"
                  />
                  <div className="min-w-0">
                    <h3 className="text-ink text-[0.9rem] leading-tight font-semibold">
                      {c.name}
                      {c.custom && (
                        <span className="editorial text-ink-3 ml-2">custom</span>
                      )}
                    </h3>
                    <p className="text-ink-2 mt-0.5 max-w-[62ch] text-[0.78rem] leading-snug">
                      {c.whatToCheck}
                    </p>
                    {reason && (
                      <p className="text-ink-2 border-rule mt-1.5 max-w-[62ch] border-l pl-2 text-[0.75rem] leading-snug italic">
                        {reason}
                      </p>
                    )}
                  </div>
                  {c.custom && (
                    <button
                      type="button"
                      aria-label={`Remove ${c.name}`}
                      disabled={disabled}
                      onClick={() =>
                        onChange(rebalance(criteria.filter((x) => x.id !== c.id)))
                      }
                      className="text-ink-3 hover:text-ink ml-auto cursor-pointer transition-colors"
                    >
                      <X className="size-4" />
                    </button>
                  )}
                </div>
              </div>

              <div className="col-start-2 mt-2.5 flex items-center gap-3 sm:col-start-3 sm:mt-0.5">
                <Slider
                  value={[c.weight]}
                  min={0}
                  max={60}
                  step={1}
                  disabled={disabled || !c.enabled}
                  aria-label={`Weight for ${c.name}`}
                  onValueChange={([next]) =>
                    onChange(redistribute(criteria, c.id, next))
                  }
                  className="min-w-0 flex-1"
                />
                <span
                  data-numeric
                  className="text-ink w-[3.25rem] shrink-0 text-right font-sans text-[0.8rem] font-semibold tabular-nums"
                >
                  {c.enabled ? `${c.weight}%` : "—"}
                </span>
              </div>
            </li>
          )
        })}
      </ul>

      {adding ? (
        <div className="border-rule mt-4 border p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="editorial text-ink-2 mb-1.5 block">Name</span>
              <input
                autoFocus
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="Sustainability commitments"
                className="border-rule bg-paper focus-visible:border-ink w-full border px-2.5 py-1.5 text-[0.85rem] focus-visible:outline-none"
              />
            </label>
            <label className="block">
              <span className="editorial text-ink-2 mb-1.5 block">
                What to check
              </span>
              <input
                value={draft.whatToCheck}
                onChange={(e) =>
                  setDraft({ ...draft, whatToCheck: e.target.value })
                }
                onKeyDown={(e) => e.key === "Enter" && addCustom()}
                placeholder="Does it address the environmental clauses?"
                className="border-rule bg-paper focus-visible:border-ink w-full border px-2.5 py-1.5 text-[0.85rem] focus-visible:outline-none"
              />
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={addCustom}
              disabled={!draft.name.trim()}
              className="editorial bg-ink text-paper hover:bg-ink-2 cursor-pointer px-3 py-2 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            >
              Add criterion
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="editorial text-ink-2 hover:text-ink cursor-pointer px-3 py-2 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          disabled
          onClick={() => setAdding(true)}
          title="This MVP evaluates the seven FPT criteria; custom criteria are not supported."
          className="editorial text-ink-2 hover:text-ink mt-4 inline-flex cursor-pointer items-center gap-2 transition-colors disabled:opacity-50"
        >
          <Plus className="size-3.5" />
          Custom criteria (not available in this MVP)
        </button>
      )}
    </div>
  )
}
