import { cn } from "@/lib/utils"
import type { Citation } from "@/api/schema"
import { excerpt } from "@/lib/quote"

import { Siglum } from "./siglum"
import { useCollation, type Tone } from "./collation"

/**
 * `R §3.1 · Pricing` — the receipt. Every judgment in the apparatus carries one, and
 * every one is live: it collates rather than navigates. A citation with no words to
 * mark still lands on its section heading.
 */
export function CitationRef({
  citation,
  sourceId,
  also,
  tone,
  className,
}: {
  citation: Citation
  sourceId: string
  /** Collated at the same time, so both witnesses align together. */
  also?: (Citation | null)[]
  /** Wash the marks in a status colour rather than the plain lemma ochre. */
  tone?: Tone
  className?: string
}) {
  const { collate, sourceId: live } = useCollation()
  const isLive = live === sourceId

  const label = citation.label || (citation.quote ? excerpt(citation.quote, 4) : "")
  const where = `${citation.witness} ${citation.label || "(no section)"}`
  const title = citation.quote ? `${where}: “${excerpt(citation.quote, 12)}”` : where
  const target: Citation = citation.quote ? citation : { ...citation, quote: citation.header || null }

  const near = citation.fuzzy && (
    <abbr
      title="Near match — the quoted words were found paraphrased or elsewhere in this section"
      aria-label="near match"
      className="text-ink-3 ml-1 no-underline"
    >
      ≈
    </abbr>
  )

  const body = (
    <>
      <Siglum of={citation.witness} className="translate-y-[0.06em]" />
      <span
        className={cn(
          "underline decoration-rule underline-offset-[3px]",
          "group-hover/cite:decoration-ink",
          isLive && "decoration-ink",
        )}
      >
        {label}
      </span>
      {near}
    </>
  )

  const look = cn(
    "group/cite inline-flex items-baseline gap-[0.3em] align-baseline",
    "font-sans text-[0.7rem] font-semibold tracking-wide whitespace-nowrap",
    isLive ? "text-ink" : "text-ink-2",
    className,
  )

  if (!target.quote) return <span className={look}>{body}</span>

  return (
    <button
      type="button"
      onClick={() => collate(sourceId, [target, ...(also ?? [])], tone ?? null)}
      title={title}
      className={cn(look, "cursor-pointer transition-colors duration-150 hover:text-ink")}
    >
      {body}
    </button>
  )
}
