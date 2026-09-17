/**
 * The sponsor's sample set, imported verbatim from the Markdown files rather
 * than transcribed, so every citation quotes text that is really there. Copied
 * into the app from `sample_data/` at the repo root so the frontend builds and
 * deploys standalone; a backend test keeps the copies byte-identical.
 *
 * All parties in these documents are fictional; the files say so themselves.
 */

import { canonical } from "@/lib/quote"

import rfp from "./samples/rfp_nordframe.md?raw"
import weak from "./samples/response_1_weak.md?raw"
import medium from "./samples/response_2_medium.md?raw"
import strong from "./samples/response_3_strong.md?raw"
import overpromise from "./samples/response_4_overpromise.md?raw"

export type SampleId = "weak" | "medium" | "strong" | "overpromise"

/**
 * `canonical` drops the `**Variant: WEAK — …**` fixture banner (it would announce the
 * verdict inside the text under review) and trailing whitespace. The backend's recordings
 * and cache are keyed on exactly this text.
 */
export const RFP_TEXT = canonical(rfp)

export const SAMPLES: Record<SampleId, { label: string; note: string; text: string }> = {
  weak: {
    label: "Weak",
    note: "Generic, pricing and timeline deferred, several requirements unaddressed",
    text: canonical(weak),
  },
  medium: {
    label: "Medium",
    note: "Good functional scope, but vague on pricing, timeline and risk",
    text: canonical(medium),
  },
  strong: {
    label: "Strong",
    note: "Addresses every requirement, priced and scheduled, risks disclosed",
    text: canonical(strong),
  },
  overpromise: {
    label: "Overpromising",
    note: "Scope balloons past the ask and contradicts a stated constraint",
    text: canonical(overpromise),
  },
}
