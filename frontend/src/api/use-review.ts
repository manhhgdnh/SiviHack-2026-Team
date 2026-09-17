import { experimental_streamedQuery as streamedQuery, skipToken, useQuery } from "@tanstack/react-query"

import type { StreamEvent } from "@/api/generated/types.gen"
import { streamReview } from "@/api/client"
import { EMPTY_PROGRESS, reduceProgress, type ReviewProgress } from "@/api/progress"
import type { ReviewInput } from "@/api/schema"

/** One run of the review: the two documents and the weights as they were when Run was pressed. */
export interface RunRequest extends ReviewInput {
  runId: number
}

type ReviewKey = readonly ["review", number, string, string]

export const reviewKey = (r: RunRequest): ReviewKey => ["review", r.runId, r.rfp, r.proposal]
const IDLE_KEY: ReviewKey = ["review", 0, "", ""]

/**
 * The review is a query keyed on the run, and it streams: `data` is the progress so far,
 * `isFetching` stays true until the `done` frame, and `data.review` is the finished edition.
 * A new run is a new key, so typing never touches the query cache and identical documents
 * still stream again (the backend's cache makes that free).
 */
export function useReview(run: RunRequest | null) {
  return useQuery<ReviewProgress, Error, ReviewProgress, ReviewKey>({
    queryKey: run ? reviewKey(run) : IDLE_KEY,
    queryFn: run
      ? streamedQuery<StreamEvent, ReviewProgress, ReviewKey>({
          streamFn: ({ signal }) => streamReview(run, signal),
          reducer: reduceProgress,
          initialValue: EMPTY_PROGRESS,
          refetchMode: "reset",
        })
      : skipToken,
    retry: false, // a retry would re-run the model
    staleTime: Infinity,
    gcTime: 30 * 60_000,
  })
}
