import { useId, useRef } from "react"

import { cn } from "@/lib/utils"
import type { Siglum as SiglumLetter } from "@/api/schema"
import { canonical } from "@/lib/quote"
import { Siglum } from "@/components/apparatus/siglum"

/**
 * A witness is declared before it can be collated. Paste it, or upload the
 * Markdown file — the format the sample data ships in. The RFP is optional and
 * says so on the pane itself, with what is lost without it.
 */
export function WitnessInput({
  of,
  title,
  role,
  placeholder,
  value,
  onChange,
  optional,
  disabled,
  className,
}: {
  of: SiglumLetter
  title: string
  role: string
  placeholder: string
  value: string
  onChange: (next: string) => void
  optional?: boolean
  disabled?: boolean
  className?: string
}) {
  const fileId = useId()
  const areaId = useId()
  const file = useRef<HTMLInputElement | null>(null)

  const lines = value.trim() === "" ? 0 : value.split("\n").length
  const words = value.trim() === "" ? 0 : value.trim().split(/\s+/).length

  return (
    <section className={cn("border-rule flex min-h-0 min-w-0 flex-col border", className)}>
      <header
        className={cn(
          "flex items-center gap-3 px-4 py-2.5",
          of === "R" ? "bg-witness-r" : "bg-witness-p",
        )}
      >
        <Siglum of={of} size="md" className="bg-cloth-text/15" />
        <div className="min-w-0 flex-1">
          <h2 className="hand-condensed text-cloth-text flex items-center gap-2 text-[0.95rem] leading-tight font-semibold tracking-wide uppercase">
            {title}
            {optional && (
              <span className="editorial text-cloth-text/70 border-cloth-text/35 border px-1.5 py-0.5 tracking-normal">
                Optional
              </span>
            )}
          </h2>
          <p className="text-cloth-text/70 text-[0.7rem] leading-tight">{role}</p>
        </div>

        <label
          htmlFor={fileId}
          className={cn(
            "editorial text-cloth-text/85 border-cloth-text/35 shrink-0 border px-2.5 py-1.5",
            "hover:bg-cloth-text/12 hover:text-cloth-text cursor-pointer transition-colors",
            "focus-within:outline-cloth-text focus-within:outline-2 focus-within:outline-offset-2",
            disabled && "pointer-events-none opacity-50",
          )}
        >
          Upload .md
          <input
            id={fileId}
            ref={file}
            type="file"
            accept=".md,.markdown,.txt,text/markdown,text/plain"
            aria-label={`Upload the ${title} as .md`}
            className="sr-only"
            disabled={disabled}
            onChange={async (e) => {
              const picked = e.target.files?.[0]
              if (!picked) return
              onChange(canonical(await picked.text()))
              if (file.current) file.current.value = ""
            }}
          />
        </label>
      </header>

      {optional && value.trim() === "" && (
        <p className="border-rule-hair text-ink-2 border-b px-4 py-2 text-[0.8rem] leading-snug">
          Without the RFP the draft is scored on six criteria alone: coverage of the client's
          requirements is skipped and Completeness vs RFP is not assessable.
        </p>
      )}

      <label htmlFor={areaId} className="sr-only">
        {title}
      </label>
      <textarea
        id={areaId}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        className={cn(
          "prose-witness bg-paper text-ink placeholder:text-ink-3 min-h-0 flex-1 resize-none px-4 py-3.5",
          "focus-visible:outline-none",
          "disabled:opacity-60",
        )}
      />

      <footer className="border-rule-hair text-ink-3 flex items-center justify-between border-t px-4 py-1.5">
        <span data-numeric className="font-sans text-[0.65rem] tabular-nums">
          {lines === 0 ? "empty" : `${lines} lines · ${words} words`}
        </span>
        {value.length > 0 && !disabled && (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label={`Clear the ${title}`}
            className="editorial hover:text-ink cursor-pointer transition-colors"
          >
            Clear
          </button>
        )}
      </footer>
    </section>
  )
}
