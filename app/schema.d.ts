// Loose contract for the frontend (BACKEND.md §9). Backend may add fields; frontend should
// ignore unknowns. Copy this next to the frontend's api/ folder, or generate a strict one
// from http://localhost/api/openapi.json — the operationIds are stable (score_score, meta_health).
export type CriterionId = string;      // one of the 7 ids, but kept as string on purpose
export type CoverageStatus = "ADDRESSED" | "PARTIAL" | "MISSING" | "CONTRADICTED";
export type Severity = "HIGH" | "MEDIUM" | "LOW";
export type RiskType = string;         // OVERCOMMIT | SCOPE_CREEP | ... — kept loose

export interface Requirement {
  id: string;
  label: string;
  rfpQuote: string;
  section?: string | null;
  grounded?: boolean;
}

export interface CoverageItem {
  requirementId: string;
  status: CoverageStatus;
  proposalQuote?: string | null;
  explanation: string;
  fix: string;
  grounded?: boolean;
}

export interface CriterionScore {
  id: CriterionId;
  label: string;
  score: number;                 // 1..5
  rationale: string;
  evidenceQuote?: string | null;
  source?: "proposal" | "rfp" | null;
  grounded?: boolean;
}

export interface RiskFinding {
  type: RiskType;
  proposalQuote: string;
  rfpQuote?: string | null;
  explanation: string;
  severity: Severity;
  grounded?: boolean;
}

export interface ScoringResult {
  overall: number;
  weights: Record<string, number>;
  scores: CriterionScore[];
  coverage: CoverageItem[];
  risks: RiskFinding[];
  requirements: Requirement[];
  meta?: {
    model?: string;
    temperature?: number;
    durationMs?: number;
    ungroundedDropped?: number;
    cacheHit?: boolean;
  };
}

export interface ScoreRequest {
  rfp: string;
  proposal: string;
  weights?: Record<string, number>;   // e.g. { pricing_clarity: 2 }
}
