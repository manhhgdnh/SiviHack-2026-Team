import { useMemo, type ComponentPropsWithoutRef, type ReactNode } from "react"
import Markdown, { type Components, type ExtraProps } from "react-markdown"
import remarkGfm from "remark-gfm"
import type { PluggableList } from "unified"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Citation, Witness } from "@/api/schema"
import { remarkLemma, type LemmaQuote } from "@/lib/remark-lemma"

import { Siglum } from "./siglum"
import { useCollation } from "./collation"

/**
 * A witness, set as a page. Markdown is set rather than shown; every block
 * carries its source line in the gutter, the way an edition numbers its
 * lines; cited passages are marked in the text itself, and the first mark
 * brings its own pane to it.
 */

/** Bring the pane to `el`, centred. Module-level, so a callback ref runs once per mount. */
function reveal(el: HTMLElement | null) {
  if (!el) return
  const pane = el.closest<HTMLElement>("[data-pane]")
  if (!pane) return
  const top =
    el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop
  pane.scrollTo({
    top: Math.max(0, top - pane.clientHeight / 2 + el.clientHeight / 2),
    behavior: "auto",
  })
}

/** A `data-*` attribute set by the remark plugin, whichever spelling reached React. */
function attr(props: object, name: string): string | undefined {
  const bag = props as Record<string, unknown>
  const camel = name.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())
  const value = bag[`data-${name}`] ?? bag[`data${camel[0].toUpperCase()}${camel.slice(1)}`]
  return value === undefined || value === null ? undefined : String(value)
}

function PendingBlock({ text }: { text: string }) {
  return (
    <div ref={reveal} className="col-span-2 grid grid-cols-[2.75rem_1fr] items-baseline">
      <span aria-hidden className="editorial text-ink-3 select-none pr-3 pt-2 text-right">
        +
      </span>
      <div className="border-ink bg-paper-inset my-1.5 mr-4 animate-[pending-settle_180ms_ease-out] border-l">
        <p className="editorial text-ink-2 px-2.5 pt-1.5">Suggested, not yet applied</p>
        <p className="prose-witness text-ink px-2.5 py-2 whitespace-pre-wrap">{text}</p>
      </div>
    </div>
  )
}

/** One block of the witness: gutter number, then the set text. */
function Row({
  props,
  space,
  marker,
  className,
  children,
}: {
  props: object
  space: string
  marker?: string
  className?: string
  children?: ReactNode
}) {
  const { pending } = useCollation()
  const line = attr(props, "line") ?? ""
  const depth = Number(attr(props, "depth") ?? 0)
  const marked = attr(props, "marked") === "true"
  const pendingHere = attr(props, "pending") === "true" ? pending : null
  const indent = (marker ? 1.5 : 0) + depth * 1.15

  return (
    <div data-line={line} className={cn("grid grid-cols-[2.75rem_1fr] items-baseline", space)}>
      <span
        data-numeric
        aria-hidden
        className={cn(
          "select-none pr-3 text-right font-sans text-[0.75rem] leading-[1.75] tabular-nums",
          marked ? "text-ink font-semibold" : "text-ink-3",
        )}
      >
        {line}
      </span>
      <div
        className={cn("prose-witness min-w-0 pr-4 break-words", className)}
        style={indent ? { paddingLeft: `${indent}em` } : undefined}
      >
        {marker && (
          <span
            aria-hidden
            className="text-ink-3 -ml-[1.5em] inline-block w-[1.5em] pr-[0.4em] text-right tabular-nums"
          >
            {marker}
          </span>
        )}
        {children}
      </div>
      {pendingHere && <PendingBlock text={pendingHere.text} />}
    </div>
  )
}

type P<T extends keyof React.JSX.IntrinsicElements> = ComponentPropsWithoutRef<T> & ExtraProps

/** The mark's wash: a requirement status tints the lemma ochre. */
const WASH: Record<string, string> = {
  addressed: "bg-mark-ready",
  partial: "bg-lemma",
  contradicted: "bg-mark-stop",
  missing: "bg-mark-ink",
}

const HEADING: Record<number, string> = {
  1: "text-ink pt-1 text-[1.05em]",
  2: "text-ink text-[0.92em]",
  3: "text-ink-2 text-[0.85em]",
}

function makeComponents(lines: string[]): Components {
  const heading =
    (level: number) =>
    ({ node: _node, children, ...props }: P<"h1">) => (
      <Row
        props={props}
        space="mt-[1.1em]"
        className={cn(
          "hand-condensed block font-semibold tracking-wide uppercase",
          HEADING[Math.min(level, 3)],
        )}
      >
        {children}
      </Row>
    )

  return {
    h1: heading(1),
    h2: heading(2),
    h3: heading(3),
    h4: heading(4),
    h5: heading(5),
    h6: heading(6),

    p: ({ node: _node, children, ...props }: P<"p">) =>
      attr(props, "block") ? (
        <Row props={props} space="mt-[0.85em]">
          {children}
        </Row>
      ) : (
        <p className="mt-[0.5em] first:mt-0">{children}</p>
      ),

    ul: ({ node: _node, children }: P<"ul">) => (
      <div role="list" className="mt-[0.6em]">
        {children}
      </div>
    ),
    ol: ({ node: _node, children }: P<"ol">) => (
      <div role="list" className="mt-[0.6em]">
        {children}
      </div>
    ),
    li: ({ node: _node, children, ...props }: P<"li">) => {
      const raw = lines[Number(attr(props, "line")) - 1] ?? ""
      const m = /^\s*([-*+]|\d+[.)])\s+/.exec(raw)
      const marker = m ? (/\d/.test(m[1]) ? m[1] : "•") : "•"
      return (
        <Row props={props} space="mt-[0.2em]" marker={marker}>
          {children}
        </Row>
      )
    },

    blockquote: ({ node: _node, children, ...props }: P<"blockquote">) => (
      <Row
        props={props}
        space="mt-[0.85em]"
        className="border-rule text-ink-2 border-l pl-3 italic"
      >
        {children}
      </Row>
    ),

    pre: ({ node: _node, children, ...props }: P<"pre">) => (
      <Row props={props} space="mt-[0.85em]">
        <pre className="bg-paper-inset overflow-x-auto px-3 py-2 font-mono text-[0.85em] leading-relaxed">
          {children}
        </pre>
      </Row>
    ),
    code: ({ node: _node, children }: P<"code">) => (
      <code className="bg-paper-inset px-1 font-mono text-[0.9em]">{children}</code>
    ),

    hr: () => (
      <div aria-hidden className="mt-[0.85em] mr-4 ml-[2.75rem]">
        <span className="bg-rule block h-px w-full" />
      </div>
    ),

    table: ({ node: _node, children, ...props }: P<"table">) => (
      <Row props={props} space="mt-[0.85em]">
        <table className="w-full border-collapse text-[0.92em] leading-snug">{children}</table>
      </Row>
    ),
    th: ({ node: _node, children }: P<"th">) => (
      <th className="border-rule text-ink border-b py-1 pr-3 text-left align-bottom font-semibold">
        {children}
      </th>
    ),
    td: ({ node: _node, children }: P<"td">) => (
      <td className="border-rule-hair border-b py-1 pr-3 align-top">{children}</td>
    ),

    strong: ({ node: _node, children }: P<"strong">) => (
      <strong className="font-semibold">{children}</strong>
    ),
    em: ({ node: _node, children }: P<"em">) => <em className="italic">{children}</em>,
    a: ({ node: _node, children, href }: P<"a">) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="decoration-rule hover:decoration-ink underline underline-offset-[3px]"
      >
        {children}
      </a>
    ),

    mark: ({ node: _node, children, ...props }: P<"mark">) => (
      <mark
        ref={attr(props, "lemma-scroll") === "true" ? reveal : undefined}
        data-lemma={attr(props, "lemma")}
        data-tone={attr(props, "tone")}
        className={cn(
          "text-ink box-decoration-clone animate-[lemma-settle_200ms_ease-out]",
          WASH[attr(props, "tone") ?? ""] ?? "bg-lemma",
        )}
      >
        {children}
      </mark>
    ),
  }
}

export function WitnessPane({
  witness,
  className,
  onHide,
}: {
  witness: Witness
  className?: string
  /** Close this witness; the rail that replaces it reopens it. */
  onHide?: () => void
}) {
  const { marks, tone, pending } = useCollation()
  const pendingHere = pending?.witness === witness.siglum ? pending : null
  const pendingQuote = pendingHere?.at?.quote ?? null

  const quotes = useMemo<LemmaQuote[]>(
    () => [
      ...marks
        .filter((m): m is Citation & { quote: string } => m.witness === witness.siglum && m.quote !== null)
        .map((m) => ({ quote: m.quote, kind: "mark" as const, tone: tone ?? undefined })),
      ...(pendingQuote ? [{ quote: pendingQuote, kind: "pending" as const }] : []),
    ],
    [marks, tone, witness.siglum, pendingQuote],
  )
  const plugins = useMemo<PluggableList>(
    () => [remarkGfm, [remarkLemma, { quotes }]],
    [quotes],
  )
  const components = useMemo(() => makeComponents(witness.text.split("\n")), [witness.text])

  return (
    <section
      className={cn("flex min-h-0 min-w-0 flex-col bg-paper", className)}
      aria-label={`${witness.title}, witness ${witness.siglum}`}
    >
      <header
        className={cn(
          "flex items-center gap-3 px-4 py-2.5",
          witness.siglum === "R" ? "bg-witness-r" : "bg-witness-p",
        )}
      >
        <Siglum of={witness.siglum} size="md" className="bg-cloth-text/15" />
        <div className="min-w-0">
          <h2 className="hand-condensed text-cloth-text text-[0.95rem] leading-tight font-semibold tracking-wide uppercase">
            {witness.title}
          </h2>
          <p className="text-cloth-text/70 text-[0.7rem] leading-tight">
            {witness.subtitle}
          </p>
        </div>
        {onHide && (
          <button
            type="button"
            onClick={onHide}
            aria-label={`Hide the ${witness.title}`}
            title={`Hide the ${witness.title}`}
            className="text-cloth-text/70 hover:bg-cloth-text/15 hover:text-cloth-text ml-auto cursor-pointer p-1.5 transition-colors"
          >
            <X className="size-4" />
          </button>
        )}
      </header>

      <div
        data-pane
        className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain py-3 [&>:first-child]:mt-0"
        tabIndex={0}
      >
        <Markdown remarkPlugins={plugins} components={components}>
          {witness.text}
        </Markdown>
        {pendingHere && !pendingHere.at && (
          <div className="grid grid-cols-[2.75rem_1fr] items-baseline">
            <PendingBlock text={pendingHere.text} />
          </div>
        )}
        <div className="h-[45%]" aria-hidden />
      </div>
    </section>
  )
}
