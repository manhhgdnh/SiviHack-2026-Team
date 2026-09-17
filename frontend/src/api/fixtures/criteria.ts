import type { Criterion } from "@/api/schema"

/**
 * The seven base criteria from the sponsor's rubric (TRACK.md, Appendix A). The ids are the
 * backend's `CriterionId` values, so a score joins its criterion without a map.
 */
export const BASE_CRITERIA: Criterion[] = [
  {
    id: "problem_understanding",
    name: "Problem Understanding",
    whatToCheck:
      "Does the proposal reflect the client's actual stated problem and goals, rather than a generic pitch?",
    enabled: true,
    weight: 15,
  },
  {
    id: "scope_clarity",
    name: "Scope & Deliverables Clarity",
    whatToCheck:
      "Are deliverables specific and unambiguous? Is it clear what is and is not included?",
    enabled: true,
    weight: 15,
  },
  {
    id: "pricing_clarity",
    name: "Pricing Clarity",
    whatToCheck:
      "Is pricing stated, broken down, and easy to understand, rather than vague or deferred?",
    enabled: true,
    weight: 14,
  },
  {
    id: "timeline_clarity",
    name: "Timeline Clarity",
    whatToCheck:
      "Are milestones and dates concrete, rather than 'in due course' or 'to be confirmed'?",
    enabled: true,
    weight: 14,
  },
  {
    id: "completeness",
    name: "Completeness vs RFP",
    whatToCheck: "Does the proposal address every requirement the RFP explicitly asked for?",
    enabled: true,
    weight: 14,
  },
  {
    id: "tone_persuasiveness",
    name: "Tone & Persuasiveness",
    whatToCheck:
      "Does it read as confident and client-focused, rather than generic boilerplate?",
    enabled: true,
    weight: 14,
  },
  {
    id: "risk_transparency",
    name: "Risk & Assumptions",
    whatToCheck: "Are assumptions, limitations and risks flagged openly rather than omitted?",
    enabled: true,
    weight: 14,
  },
]
