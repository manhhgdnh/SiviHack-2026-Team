import {
  AlignmentType,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from "docx"

import type { Criterion, Issue, Review, Witness } from "@/api/schema"
import { CONSTRAINT_LABEL, FINDING_LABEL } from "@/features/review/apparatus"
import { NO_VERDICT_LABEL, VERDICT_LABEL } from "@/lib/score"

/**
 * The review as a document to hand to the proposal writer. One report model, two renderers:
 * Markdown for anything that reads text, Word for anyone who does not.
 */

type Run = { text: string; bold?: boolean; italic?: boolean }
type Block =
  | { kind: "h"; level: 1 | 2 | 3; text: string }
  | { kind: "p"; runs: Run[] }
  | { kind: "li"; runs: Run[] }
  | { kind: "table"; header: string[]; rows: string[][] }

const t = (text: string): Run => ({ text })
const b = (text: string): Run => ({ text, bold: true })
const i = (text: string): Run => ({ text, italic: true })

const STATUS_WORD = { addressed: "Addressed", partial: "Partial", missing: "Not found", contradicted: "Contradicted" }
const SEVERITY_WORD = { must: "Must fix", should: "Should fix", optional: "Optional" }

/** The proposal's own title line, if it has one. */
function titleOf(text: string): string | null {
  const line = text.split("\n").find((l) => /^#\s+/.test(l))
  return line ? line.replace(/^#\s+/, "").replace(/[*_`]/g, "").trim() : null
}

function reading(issue: Issue, names: Map<string, string>): string {
  const name = names.get(issue.criterionId) ?? issue.criterionId
  if (issue.kind === "violation") return `Constraint · ${CONSTRAINT_LABEL[issue.constraintKind]}`
  if (issue.kind === "finding") return `${name} · ${FINDING_LABEL[issue.findingType]}`
  return name
}

function where(issue: Issue): string {
  const parts = [
    issue.location ? `P ${issue.location.label}` : null,
    issue.against ? `R ${issue.against.label}` : null,
  ].filter(Boolean)
  return parts.length ? ` (${parts.join(", ")})` : ""
}

export function reportBlocks(
  review: Review,
  criteria: Criterion[],
  score: number | null,
  witnesses: { R: Witness; P: Witness },
): Block[] {
  const names = new Map(criteria.map((c) => [c.id, c.name]))
  const verdict = score === null ? NO_VERDICT_LABEL : VERDICT_LABEL[review.verdict ?? "not-ready"]
  const title = titleOf(witnesses.P.text)
  const blocks: Block[] = []

  blocks.push({ kind: "h", level: 1, text: `Proposal review — ${verdict}` })
  blocks.push({
    kind: "p",
    runs: [
      ...(title ? [b(title), t("  ·  ")] : []),
      t(`Overall ${score === null ? "—" : score.toFixed(1)} / 5  ·  reviewed ${new Date().toISOString().slice(0, 10)}  ·  ${review.meta.model}`),
    ],
  })
  if (review.partial) {
    blocks.push({ kind: "p", runs: [b("Partial review. "), t(review.error ?? review.warnings.join("; "))] })
  }

  blocks.push({ kind: "h", level: 2, text: "Scores" })
  blocks.push({
    kind: "table",
    header: ["Criterion", "Score", "Weight", "Comment"],
    rows: criteria
      .filter((c) => c.enabled)
      .map((c) => {
        const s = review.criteria.find((x) => x.criterionId === c.id)
        const comment = s ? [s.weakness, s.strength ? `Strength: ${s.strength}` : null].filter(Boolean).join(" ") : ""
        return [c.name, s?.score != null ? `${s.score}/5` : `— ${s?.note ?? ""}`.trim(), `${c.weight} %`, comment]
      }),
  })
  blocks.push({ kind: "p", runs: [i("The overall is the weighted mean of the scored criteria, computed in code; the weights are the ones shown.")] })

  blocks.push({ kind: "h", level: 2, text: `Requirement coverage (${review.requirements.length} asked)` })
  if (review.requirements.length === 0) {
    blocks.push({ kind: "p", runs: [t(review.error ? "Coverage was not assessed: the analysis call failed." : "No RFP was provided, so coverage was not checked.")] })
  } else {
    blocks.push({
      kind: "table",
      header: ["Requirement", "Status", "Where the draft answers", "Note"],
      rows: review.requirements.map((r) => [
        `${r.label} — "${r.text}"`,
        review.error ? "not assessed" : STATUS_WORD[r.status],
        r.answeredAt ? `P ${r.answeredAt.label}` : "no answering passage",
        review.error ? "" : r.note,
      ]),
    })
  }
  if (review.constraints.length > 0) {
    blocks.push({ kind: "h", level: 3, text: "Constraints" })
    for (const c of review.constraints) {
      const violated = review.issues.some((x) => x.id === `vio-${c.id}`)
      blocks.push({
        kind: "li",
        runs: [b(`${CONSTRAINT_LABEL[c.kind]}: `), t(c.label), t(` — "${c.source.quote ?? ""}" (R ${c.source.label}) — `), b(violated ? "violated" : "respected")],
      })
    }
  }

  const open = review.issues
  const groups: { title: string; items: Issue[] }[] = [
    { title: "Violates a client constraint", items: open.filter((x) => x.kind === "violation") },
    ...(["must", "should", "optional"] as const).map((sev) => ({
      title: SEVERITY_WORD[sev],
      items: open.filter((x) => x.kind !== "violation" && x.severity === sev),
    })),
  ].filter((g) => g.items.length > 0)
  blocks.push({ kind: "h", level: 2, text: `Issues (${open.length})` })
  if (open.length === 0) blocks.push({ kind: "p", runs: [t("No issues found.")] })
  for (const g of groups) {
    blocks.push({ kind: "h", level: 3, text: `${g.title} (${g.items.length})` })
    for (const issue of g.items) {
      blocks.push({ kind: "li", runs: [b(issue.lemma), t(` ] ${reading(issue, names)}${where(issue)}`)] })
      if (issue.kind === "violation" && issue.against?.quote) {
        blocks.push({ kind: "p", runs: [t("R asks: "), i(`"${issue.against.quote}"`)] })
      }
      if (issue.quoted) blocks.push({ kind: "p", runs: [t("The draft says: "), i(`"${issue.quoted}"`)] })
      blocks.push({ kind: "p", runs: [t(issue.kind === "violation" ? "Why it breaks the constraint: " : "Why it matters: "), t(issue.whyItMatters)] })
      blocks.push({ kind: "p", runs: [t("Suggested fix: "), b(issue.suggestedFix ?? "no fix suggested")] })
    }
  }

  if (review.suggestedWeights.length > 0) {
    blocks.push({ kind: "h", level: 2, text: "Weights the RFP suggests" })
    for (const w of review.suggestedWeights) {
      blocks.push({ kind: "li", runs: [b(`${names.get(w.criterionId) ?? w.criterionId}: `), t(`${Math.round(w.weight)} % — ${w.reason}`)] })
    }
  }

  blocks.push({
    kind: "p",
    runs: [
      i(`Every quote was verified against the source text by code (${review.meta.fuzzyMatched} near matches, ${review.meta.ungroundedDropped} unverifiable quotes dropped). Generated by Proposal Scorer.`),
    ],
  })
  return blocks
}

/* ---- Markdown ---------------------------------------------------------------------------- */

const cell = (s: string) => s.replace(/\|/g, "\\|").replace(/\n+/g, " ")
const md = (runs: Run[]) =>
  runs.map((r) => (r.bold ? `**${r.text}**` : r.italic ? `*${r.text}*` : r.text)).join("")

export function toMarkdown(blocks: Block[]): string {
  const out: string[] = []
  for (const blk of blocks) {
    switch (blk.kind) {
      case "h":
        out.push(`${"#".repeat(blk.level)} ${blk.text}`, "")
        break
      case "p":
        out.push(md(blk.runs), "")
        break
      case "li":
        out.push(`- ${md(blk.runs)}`)
        break
      case "table":
        out.push(
          `| ${blk.header.map(cell).join(" | ")} |`,
          `| ${blk.header.map(() => "---").join(" | ")} |`,
          ...blk.rows.map((row) => `| ${row.map(cell).join(" | ")} |`),
          "",
        )
        break
    }
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n"
}

/* ---- Word --------------------------------------------------------------------------------- */

const runs = (rs: Run[]) => rs.map((r) => new TextRun({ text: r.text, bold: r.bold, italics: r.italic }))
const HEADING = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3 } as const

export async function toDocx(blocks: Block[]): Promise<Blob> {
  const children = blocks.map((blk) => {
    switch (blk.kind) {
      case "h":
        return new Paragraph({ text: blk.text, heading: HEADING[blk.level] })
      case "p":
        return new Paragraph({ children: runs(blk.runs), spacing: { after: 120 } })
      case "li":
        return new Paragraph({ children: runs(blk.runs), bullet: { level: 0 } })
      case "table":
        return new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: [
            new TableRow({
              tableHeader: true,
              children: blk.header.map(
                (h) =>
                  new TableCell({
                    children: [new Paragraph({ children: [new TextRun({ text: h, bold: true })] })],
                  }),
              ),
            }),
            ...blk.rows.map(
              (row) =>
                new TableRow({
                  children: row.map(
                    (c) => new TableCell({ children: [new Paragraph({ text: c, alignment: AlignmentType.LEFT })] }),
                  ),
                }),
            ),
          ],
        })
    }
  })
  const doc = new Document({ sections: [{ children }] })
  return Packer.toBlob(doc)
}

/* ---- the file ------------------------------------------------------------------------------ */

export function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function reportFilename(witnesses: { R: Witness; P: Witness }, ext: "md" | "docx"): string {
  const slug = (titleOf(witnesses.P.text) ?? "proposal")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48)
  return `review-${slug || "proposal"}-${new Date().toISOString().slice(0, 10)}.${ext}`
}
