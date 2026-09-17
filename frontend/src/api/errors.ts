export type ReviewErrorCode =
  | "empty-input"
  | "unknown-document"
  | "transport"
  | "upstream"
  | "contract"

/**
 * Every failure the UI can show. `upstream` is the backend saying no (a 5xx, an `error`
 * frame, a budget refusal); `contract` is the backend answering in a shape the generated
 * schemas reject, which means the client is stale against `app/openapi.json`.
 */
export class ReviewError extends Error {
  code: ReviewErrorCode
  /** The pipeline stage the backend named, when it did. */
  stage: string | null

  constructor(message: string, code: ReviewErrorCode, stage: string | null = null) {
    super(message)
    this.name = "ReviewError"
    this.code = code
    this.stage = stage
  }
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError"
