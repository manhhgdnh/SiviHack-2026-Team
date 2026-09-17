import type { EventSourceMessage } from "eventsource-parser"
import { EventSourceParserStream } from "eventsource-parser/stream"

import type { ScoreRequest, StreamEvent } from "@/api/generated/types.gen"
import { zScoreRequest, zStreamEvent } from "@/api/generated/zod.gen"
import { isAbort, ReviewError } from "@/api/errors"

/**
 * POST /score/stream as a typed async iterator. `EventSource` cannot POST, so this reads the
 * body as a stream: bytes → text → SSE messages → validated frames. Every frame goes through
 * the generated zod schema, so a backend that drifted from `app/openapi.json` surfaces as a
 * `contract` error naming the field, never as a crash deeper in the app.
 */

/** The backend pings every 15 s; this long without a frame or a ping is a dead connection. */
const IDLE_MS = 60_000

/** nginx or the Vite proxy answering for a backend that is not there. */
export const UNREACHABLE =
  "The review service could not be reached. Is the backend running? Check it, then press Run review again."
export const isGateway = (status: number) => status === 502 || status === 503 || status === 504

export async function detail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === "string") return body.detail
  } catch {
    // not JSON
  }
  return `${res.status} ${res.statusText}`.trim()
}

export async function* streamScore(
  api: string,
  body: ScoreRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent, void, undefined> {
  const idle = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const arm = () => {
    clearTimeout(timer)
    timer = setTimeout(
      () =>
        idle.abort(
          new ReviewError(
            `No word from the review service for ${IDLE_MS / 1000} seconds. Check the backend and try again.`,
            "transport",
          ),
        ),
      IDLE_MS,
    )
  }
  // Byte level, so `: ping` comments (which the parser swallows) also reset the clock.
  const watchdog = new TransformStream<Uint8Array<ArrayBuffer>, BufferSource>({
    transform(chunk, controller) {
      arm()
      controller.enqueue(chunk)
    },
  })
  const failed = (): ReviewError | null =>
    idle.signal.reason instanceof ReviewError ? idle.signal.reason : null

  let res: Response
  try {
    arm()
    res = await fetch(`${api}/score/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(zScoreRequest.parse(body)),
      signal: signal ? AbortSignal.any([signal, idle.signal]) : idle.signal,
    })
  } catch (e) {
    clearTimeout(timer)
    const dead = failed()
    if (dead) throw dead
    if (isAbort(e)) throw e
    throw new ReviewError(UNREACHABLE, "transport")
  }
  if (isGateway(res.status)) {
    clearTimeout(timer)
    throw new ReviewError(UNREACHABLE, "transport")
  }
  if (res.status === 400) {
    clearTimeout(timer)
    throw new ReviewError(await detail(res), "empty-input")
  }
  if (!res.ok || !res.body) {
    clearTimeout(timer)
    throw new ReviewError(
      `The review service failed before it could answer: ${await detail(res)}. Press Run review to try again.`,
      "upstream",
    )
  }

  const reader = res.body
    .pipeThrough(watchdog)
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream({ onError: "terminate" }))
    .getReader()
  try {
    for (;;) {
      let next: ReadableStreamReadResult<EventSourceMessage>
      try {
        next = await reader.read()
      } catch (e) {
        const dead = failed()
        if (dead) throw dead
        if (e instanceof ReviewError || isAbort(e)) throw e
        throw new ReviewError(
          "The connection dropped while the review was streaming. Press Run review to try again.",
          "transport",
        )
      }
      if (next.done) {
        throw new ReviewError(
          "The stream ended before the review was done. Press Run review to try again.",
          "upstream",
        )
      }
      const frame = parseFrame(next.value)
      if (frame.event === "error") {
        throw new ReviewError(frame.data.error, "upstream", frame.data.stage)
      }
      yield frame
      if (frame.event === "done") return
    }
  } finally {
    clearTimeout(timer)
    reader.cancel().catch(() => {}) // frees the socket if the consumer stops early
  }
}

function parseFrame(msg: EventSourceMessage): StreamEvent {
  const name = msg.event ?? "message"
  let data: unknown
  try {
    data = JSON.parse(msg.data)
  } catch {
    throw new ReviewError(
      `The review service sent a frame that is not JSON (event "${name}").`,
      "contract",
    )
  }
  const parsed = zStreamEvent.safeParse({ event: name, data })
  if (!parsed.success) {
    const issue = parsed.error.issues[0]
    const where = issue ? ` (${[name, ...issue.path].join(".")}: ${issue.message})` : ""
    throw new ReviewError(
      `The review service answered in a shape this build does not understand${where}. Regenerate the client from app/openapi.json.`,
      "contract",
    )
  }
  return parsed.data as StreamEvent
}
