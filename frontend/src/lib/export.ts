import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  HeadingLevel,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from "docx"

import type { Criterion, Issue, RequirementStatus, Review, Witness } from "@/api/schema"
import { CONSTRAINT_LABEL, FINDING_LABEL } from "@/features/review/apparatus"
import { NO_VERDICT_LABEL, VERDICT_LABEL } from "@/lib/score"

/**
 * The review as a document to hand to the proposal writer. One report model, two renderers:
 * Markdown for anything that reads text, Word for anyone who does not. The Word file keeps
 * the edition's manners: paper, ink, the binding colours for the verdict and the statuses,
 * quotes set apart with a rule, the fix in an inset box.
 */

type Tone = "ink" | "muted" | "stop" | "fix" | "ready"
type Run = { text: string; bold?: boolean; italic?: boolean; tone?: Tone }
type Block =
  | { kind: "h"; level: 1 | 2 | 3; text: string; tone?: Tone }
  | { kind: "p"; runs: Run[] }
  | { kind: "meta"; runs: Run[] }
  | { kind: "quote"; label: string; text: string }
  | { kind: "fix"; text: string }
  | { kind: "li"; runs: Run[] }
  | { kind: "table"; header: string[]; widths: number[]; rows: Run[][][] }
  | { kind: "rule" }

const t = (text: string, tone?: Tone): Run => ({ text, tone })
const b = (text: string, tone?: Tone): Run => ({ text, bold: true, tone })
const i = (text: string, tone?: Tone): Run => ({ text, italic: true, tone })

const STATUS_WORD: Record<RequirementStatus, string> = {
  addressed: "Addressed",
  partial: "Partial",
  missing: "Not found",
  contradicted: "Contradicted",
}
const STATUS_TONE: Record<RequirementStatus, Tone> = {
  addressed: "ready",
  partial: "fix",
  missing: "ink",
  contradicted: "stop",
}
const SEVERITY_WORD = { must: "Must fix", should: "Should fix", optional: "Optional" } as const
const SEVERITY_TONE: Record<"must" | "should" | "optional", Tone> = { must: "stop", should: "fix", optional: "muted" }
const VERDICT_TONE = { ready: "ready", fix: "fix", "not-ready": "stop" } as const

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
  return parts.length ? parts.join(", ") : ""
}

export function reportBlocks(
  review: Review,
  criteria: Criterion[],
  score: number | null,
  witnesses: { R: Witness; P: Witness },
): Block[] {
  const names = new Map(criteria.map((c) => [c.id, c.name]))
  const verdict = score === null || !review.verdict ? NO_VERDICT_LABEL : VERDICT_LABEL[review.verdict]
  const tone: Tone = score === null || !review.verdict ? "ink" : VERDICT_TONE[review.verdict]
  const title = titleOf(witnesses.P.text)
  const today = new Date().toISOString().slice(0, 10)
  const blocks: Block[] = []

  blocks.push({ kind: "meta", runs: [t(`Proposal review  ·  ${today}  ·  ${review.meta.model}`)] })
  blocks.push({ kind: "h", level: 1, text: `${verdict}  ${score === null ? "—" : score.toFixed(1)} / 5`, tone })
  if (title) blocks.push({ kind: "p", runs: [b(title)] })
  if (review.partial) {
    blocks.push({ kind: "p", runs: [b("Partial review. ", "fix"), t(review.error ?? review.warnings.join("; "))] })
  }
  blocks.push({ kind: "rule" })

  blocks.push({ kind: "h", level: 2, text: "Scores" })
  blocks.push({
    kind: "table",
    header: ["Criterion", "Score", "Weight", "Comment"],
    widths: [26, 9, 9, 56],
    rows: criteria
      .filter((c) => c.enabled)
      .map((c) => {
        const s = review.criteria.find((x) => x.criterionId === c.id)
        const comment: Run[] = s
          ? [t(s.weakness), ...(s.strength ? [t(" "), i(`Strength: ${s.strength}`, "muted")] : [])]
          : [t("")]
        return [
          [b(c.name)],
          [s?.score != null ? b(`${s.score} / 5`) : t(`— ${s?.note ?? ""}`.trim(), "muted")],
          [t(`${c.weight} %`)],
          comment,
        ]
      }),
  })
  blocks.push({
    kind: "meta",
    runs: [t("The overall is the weighted mean of the scored criteria, computed in code from the weights shown.")],
  })

  const tally = (["addressed", "partial", "missing", "contradicted"] as const)
    .map((s) => ({ s, n: review.requirements.filter((r) => r.status === s).length }))
    .filter(({ n }) => n > 0)
    .map(({ s, n }) => `${n} ${STATUS_WORD[s].toLowerCase()}`)
  blocks.push({
    kind: "h",
    level: 2,
    text: `Requirement coverage (${review.requirements.length} asked${tally.length && !review.error ? " · " + tally.join(" · ") : ""})`,
  })
  if (review.requirements.length === 0) {
    blocks.push({
      kind: "p",
      runs: [t(review.error ? "Coverage was not assessed: the analysis call failed." : "No RFP was provided, so coverage was not checked.")],
    })
  } else {
    blocks.push({
      kind: "table",
      header: ["Requirement", "Status", "Where the draft answers", "Note"],
      widths: [36, 12, 20, 32],
      rows: review.requirements.map((r) => [
        [b(r.label), t(" "), i(`“${r.text}”`, "muted")],
        [review.error ? t("not assessed", "muted") : b(STATUS_WORD[r.status], STATUS_TONE[r.status])],
        [r.answeredAt ? t(`P ${r.answeredAt.label}`) : i("no answering passage", "muted")],
        [t(review.error ? "" : r.note)],
      ]),
    })
  }
  if (review.constraints.length > 0) {
    blocks.push({ kind: "h", level: 3, text: "Constraints" })
    for (const c of review.constraints) {
      const violated = review.issues.some((x) => x.id === `vio-${c.id}`)
      blocks.push({
        kind: "li",
        runs: [
          b(`${CONSTRAINT_LABEL[c.kind]} — ${c.label}: `),
          i(`“${c.source.quote ?? ""}”`, "muted"),
          t(` (R ${c.source.label}) — `),
          violated ? b("violated", "stop") : b("respected", "ready"),
        ],
      })
    }
  }

  const open = review.issues
  const groups: { title: string; tone: Tone; items: Issue[] }[] = [
    { title: "Violates a client constraint", tone: "stop" as Tone, items: open.filter((x) => x.kind === "violation") },
    ...(["must", "should", "optional"] as const).map((sev) => ({
      title: SEVERITY_WORD[sev],
      tone: SEVERITY_TONE[sev],
      items: open.filter((x) => x.kind !== "violation" && x.severity === sev),
    })),
  ].filter((g) => g.items.length > 0)
  blocks.push({ kind: "h", level: 2, text: `Issues (${open.length})` })
  if (open.length === 0) blocks.push({ kind: "p", runs: [t("No issues found: every requirement is addressed and nothing was flagged.")] })
  for (const g of groups) {
    blocks.push({ kind: "h", level: 3, text: `${g.title} (${g.items.length})`, tone: g.tone })
    for (const issue of g.items) {
      const at = where(issue)
      blocks.push({
        kind: "p",
        runs: [b(issue.lemma), t(`  ]  ${reading(issue, names)}`, "muted"), ...(at ? [t(`  ·  ${at}`, "muted")] : [])],
      })
      if (issue.kind === "violation" && issue.against?.quote) {
        blocks.push({ kind: "quote", label: "The RFP asks", text: issue.against.quote })
      }
      if (issue.quoted) blocks.push({ kind: "quote", label: "The draft says", text: issue.quoted })
      blocks.push({
        kind: "p",
        runs: [b(issue.kind === "violation" ? "Why it breaks the constraint  " : "Why it matters  ", "muted"), t(issue.whyItMatters)],
      })
      blocks.push({ kind: "fix", text: issue.suggestedFix ?? "No fix suggested." })
    }
  }

  if (review.suggestedWeights.length > 0) {
    blocks.push({ kind: "h", level: 2, text: "Weights the RFP suggests" })
    for (const w of review.suggestedWeights) {
      blocks.push({
        kind: "li",
        runs: [b(`${names.get(w.criterionId) ?? w.criterionId}  ${Math.round(w.weight)} %`), t(` — ${w.reason}`)],
      })
    }
  }

  blocks.push({ kind: "rule" })
  blocks.push({
    kind: "meta",
    runs: [
      t(
        `Every quote was verified against the source text by code: ${review.meta.fuzzyMatched} near matches, ${review.meta.ungroundedDropped} unverifiable quotes dropped. Generated by Proposal Scorer.`,
      ),
    ],
  })
  return blocks
}

/* ---- Markdown ---------------------------------------------------------------------------- */

const cell = (s: string) => s.replace(/\|/g, "\\|").replace(/\n+/g, " ")
const md = (runs: Run[]) =>
  runs
    .map((r) => (r.text.trim() === "" ? r.text : r.bold ? `**${r.text.trim()}**` : r.italic ? `*${r.text.trim()}*` : r.text))
    .join("")
    .replace(/\*\*\s+/g, "** ")

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
      case "meta":
        out.push(`*${blk.runs.map((r) => r.text).join("")}*`, "")
        break
      case "quote":
        out.push(`> **${blk.label}:** *${blk.text}*`, "")
        break
      case "fix":
        out.push(`**Suggested fix:** ${blk.text}`, "")
        break
      case "li":
        out.push(`- ${md(blk.runs)}`)
        break
      case "table":
        out.push(
          `| ${blk.header.map(cell).join(" | ")} |`,
          `| ${blk.header.map(() => "---").join(" | ")} |`,
          ...blk.rows.map((row) => `| ${row.map((c) => cell(md(c))).join(" | ")} |`),
          "",
        )
        break
      case "rule":
        out.push("---", "")
        break
    }
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n"
}

/* ---- Word --------------------------------------------------------------------------------- */

const COLOR: Record<Tone, string> = { ink: "141210", muted: "6B645A", stop: "9E1B32", fix: "8A5A00", ready: "1A5632" }
const PAPER_INSET = "F3F1EA"
const RULE = "C9C3B6"
const SERIF = "Georgia"
const SANS = "Arial"
const PAGE = { width: 11906, height: 16838, margin: 1134 } // A4, 2 cm
const TEXT_WIDTH = PAGE.width - 2 * PAGE.margin
const HEADING = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3 } as const

const runs = (rs: Run[], base: { size?: number; font?: string } = {}) =>
  rs.map(
    (r) =>
      new TextRun({
        text: r.text,
        bold: r.bold,
        italics: r.italic,
        color: r.tone ? COLOR[r.tone] : undefined,
        size: base.size,
        font: base.font,
      }),
  )
const edge = (color: string, size: number) => ({ style: BorderStyle.SINGLE, size, color })
const label = (text: string) =>
  new TextRun({ text: text.toUpperCase(), size: 15, bold: true, color: COLOR.muted, characterSpacing: 20 })

function cellOf(content: Run[], width: number, header = false): TableCell {
  return new TableCell({
    width: { size: width, type: WidthType.PERCENTAGE },
    shading: header ? { type: ShadingType.CLEAR, fill: PAPER_INSET, color: "auto" } : undefined,
    margins: { top: 80, bottom: 80, left: 110, right: 110 },
    children: [new Paragraph({ children: runs(content, { size: header ? 17 : 19 }), alignment: AlignmentType.LEFT })],
  })
}

function render(blk: Block): Paragraph | Table {
  switch (blk.kind) {
    case "h":
      return new Paragraph({
        heading: HEADING[blk.level],
        children: [new TextRun({ text: blk.text, color: blk.tone ? COLOR[blk.tone] : undefined })],
      })
    case "p":
      return new Paragraph({ children: runs(blk.runs), spacing: { after: 120 } })
    case "meta":
      return new Paragraph({ children: runs(blk.runs, { size: 17 }).map((r) => r), spacing: { after: 160 } })
    case "quote":
      return new Paragraph({
        indent: { left: 360 },
        border: { left: { ...edge(RULE, 12), space: 10 } },
        spacing: { before: 60, after: 120 },
        children: [label(blk.label), new TextRun({ text: blk.text, italics: true, font: SERIF, size: 21, break: 1 })],
      })
    case "fix":
      return new Paragraph({
        indent: { left: 360, right: 360 },
        shading: { type: ShadingType.CLEAR, fill: PAPER_INSET, color: "auto" },
        border: { left: { ...edge(COLOR.ink, 18), space: 10 } },
        spacing: { before: 60, after: 240 },
        children: [label("Suggested fix"), new TextRun({ text: blk.text, font: SERIF, size: 21, break: 1 })],
      })
    case "li":
      return new Paragraph({ children: runs(blk.runs), bullet: { level: 0 }, spacing: { after: 80 } })
    case "rule":
      return new Paragraph({ border: { bottom: { ...edge(RULE, 6), space: 4 } }, spacing: { before: 120, after: 240 } })
    case "table": {
      const widths = blk.widths.map((w) => Math.round((TEXT_WIDTH * w) / 100))
      return new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        columnWidths: widths,
        borders: {
          top: edge(RULE, 6),
          bottom: edge(RULE, 6),
          left: edge(RULE, 6),
          right: edge(RULE, 6),
          insideHorizontal: edge(RULE, 4),
          insideVertical: edge(RULE, 4),
        },
        rows: [
          new TableRow({ tableHeader: true, children: blk.header.map((h, n) => cellOf([b(h, "muted")], blk.widths[n], true)) }),
          ...blk.rows.map((row) => new TableRow({ children: row.map((c, n) => cellOf(c, blk.widths[n])) })),
        ],
      })
    }
  }
}

export async function toDocx(blocks: Block[], title: string): Promise<Blob> {
  const doc = new Document({
    creator: "Proposal Scorer",
    title,
    styles: {
      default: { document: { run: { font: SANS, size: 20, color: COLOR.ink } } },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 52, bold: true, font: SANS, color: COLOR.ink },
          paragraph: { spacing: { before: 120, after: 120 } },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 28, bold: true, font: SANS, color: COLOR.ink },
          paragraph: { spacing: { before: 400, after: 140 }, border: { bottom: { ...edge(COLOR.ink, 8), space: 4 } } },
        },
        {
          id: "Heading3",
          name: "Heading 3",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 22, bold: true, font: SANS, color: COLOR.muted },
          paragraph: { spacing: { before: 280, after: 100 } },
        },
      ],
    },
    sections: [
      {
        properties: { page: { size: { width: PAGE.width, height: PAGE.height }, margin: { top: PAGE.margin, right: PAGE.margin, bottom: PAGE.margin, left: PAGE.margin } } },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: "Proposal Scorer  ·  page ", size: 16, color: COLOR.muted }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, color: COLOR.muted }),
                  new TextRun({ text: " of ", size: 16, color: COLOR.muted }),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: COLOR.muted }),
                ],
              }),
            ],
          }),
        },
        children: blocks.map(render),
      },
    ],
  })
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
