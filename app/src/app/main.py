"""FastAPI routes. nginx strips /api, so these are /health, /score, /score/stream, /rfp/extract.

POST /score          blocking: the full ScoringResult (200 even when `partial`); 400 blank
                     proposal; 502 when the LLM call failed after its retry.
POST /score/stream   Server-Sent Events, one frame per stage (schema.StreamEvent):
                     sections → requirements → coverage → scores → findings → done, or `error`
                     (terminal). FastAPI's native SSE adds `: ping` every 15 s while a call is
                     in flight.
POST /rfp/extract    call 1 only; same cache as a full run, so a run right after costs nothing.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.logs import configure
from app.pipeline import extract_requirements, run, score_proposal
from app.schema import (
    ErrorDetail,
    ErrorEvent,
    ExtractRequest,
    RequirementsEvent,
    ScoreRequest,
    ScoringResult,
    StreamEvent,
)

log = logging.getLogger(__name__)
configure()


def unique_id(route: APIRoute) -> str:
    """Stable operationIds (`score_score`, `score_stream`, `rfp_extract`, `meta_health`)."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


app = FastAPI(title="Proposal Scorer", generate_unique_id_function=unique_id)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BLANK_PROPOSAL = {
    "model": ErrorDetail,
    "description": "The proposal is blank (the RFP is optional).",
}
BLANK_RFP = {"model": ErrorDetail, "description": "The RFP is blank."}
UPSTREAM = {"model": ErrorDetail, "description": "The LLM call failed after its retry."}


def valid_score_request(req: ScoreRequest) -> ScoreRequest:
    """A dependency, so the stream route answers a plain-JSON 400 before any byte streams."""
    if not req.proposal.strip():
        raise HTTPException(400, "proposal is required (rfp is optional)")
    return req


@app.get("/health", tags=["meta"])
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/score", tags=["score"], responses={400: BLANK_PROPOSAL, 502: UPSTREAM})
async def score(req: Annotated[ScoreRequest, Depends(valid_score_request)]) -> ScoringResult:
    try:
        return await score_proposal(req.rfp, req.proposal, req.weights)
    except Exception as e:
        log.exception("scoring failed")
        raise HTTPException(502, f"scoring failed: {type(e).__name__}: {e}") from e


@app.post(
    "/score/stream",
    tags=["score"],
    response_class=EventSourceResponse,
    responses={
        # `model` here puts StreamEvent into components and into the text/event-stream schema.
        200: {
            "model": StreamEvent,
            "description": "One frame per pipeline stage; `done` and `error` are terminal.",
        },
        # The 400 body is plain JSON, not a frame, so its media type is spelled out.
        400: {
            "description": BLANK_PROPOSAL["description"],
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorDetail"}}
            },
        },
    },
)
async def stream(
    req: Annotated[ScoreRequest, Depends(valid_score_request)],
) -> AsyncIterator[ServerSentEvent]:
    """FastAPI frames each ServerSentEvent, sets Cache-Control / X-Accel-Buffering and pings
    while the generator is silent. A failure mid-stream is an `error` frame, never a dropped
    socket."""
    stage = "sections"
    try:
        async for event, payload in run(req.rfp, req.proposal, req.weights):
            stage = event
            yield ServerSentEvent(event=event, data=payload)
    except Exception as e:
        log.exception("pipeline failed during stream")
        yield ServerSentEvent(
            event="error", data=ErrorEvent(stage=stage, error=f"{type(e).__name__}: {e}")
        )


@app.post("/rfp/extract", tags=["rfp"], responses={400: BLANK_RFP, 502: UPSTREAM})
async def extract(req: ExtractRequest) -> RequirementsEvent:
    if not req.rfp.strip():
        raise HTTPException(400, "rfp is required")
    try:
        return await extract_requirements(req.rfp)
    except Exception as e:
        log.exception("extraction failed")
        raise HTTPException(502, f"extraction failed: {type(e).__name__}: {e}") from e
