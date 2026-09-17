"""FastAPI routes. nginx strips /api, so these are /health, /score and /score/stream.

POST /score         blocking; the full ScoringResult (200 even when `partial: true`).
POST /score/stream  Server-Sent Events, one event per pipeline stage:
                    sections → requirements → scores → findings → done   (or error)
                    plus a `: ping` comment every 15 s so proxies keep the connection.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.pipeline import Event, run, score_proposal
from app.schema import ErrorEvent, ScoreRequest, ScoringResult

log = logging.getLogger(__name__)
PING_SECONDS = 15.0


def unique_id(route: APIRoute) -> str:
    """Stable operationIds (`score_score`, `score_stream`, `meta_health`) for a generated TS client."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


app = FastAPI(title="Proposal Scorer", generate_unique_id_function=unique_id)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _validate(req: ScoreRequest) -> None:
    if not req.proposal.strip():
        raise HTTPException(400, "proposal is required (rfp is optional)")


def _frame(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


async def sse(events: AsyncIterator[Event], ping: float = PING_SECONDS) -> AsyncIterator[str]:
    """Serialise pipeline events as SSE frames; keep the connection alive while an LLM
    call is in flight; turn an exception into an `error` event instead of a dropped socket."""
    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def pump() -> None:
        stage = "sections"
        try:
            async for event, payload in events:
                stage = event
                await queue.put((event, payload))
        except Exception as e:
            log.exception("pipeline failed during stream")
            await queue.put(("error", ErrorEvent(stage=stage, error=f"{type(e).__name__}: {e}")))
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), ping)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is None:
                return
            yield _frame(*item)
    finally:
        task.cancel()


@app.get("/health", tags=["meta"])
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/score", response_model=ScoringResult, tags=["score"])
async def score(req: ScoreRequest) -> ScoringResult:
    _validate(req)
    try:
        return await score_proposal(req.rfp, req.proposal, req.weights)
    except Exception as e:
        log.exception("scoring failed")
        raise HTTPException(502, f"scoring failed: {type(e).__name__}: {e}") from e


@app.post("/score/stream", tags=["score"])
async def stream(req: ScoreRequest) -> StreamingResponse:
    _validate(req)
    return StreamingResponse(
        sse(run(req.rfp, req.proposal, req.weights)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: do not buffer this response
        },
    )
