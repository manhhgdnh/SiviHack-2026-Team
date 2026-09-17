"""FastAPI routes (BACKEND.md §16). nginx strips /api, so these are /health and /score."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.pipeline import score_proposal
from app.schema import ScoreRequest, ScoringResult

log = logging.getLogger(__name__)


def unique_id(route: APIRoute) -> str:
    """Stable operationIds (`score_score`, `meta_health`) for a generated TS client."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


app = FastAPI(title="Proposal Scorer v0", generate_unique_id_function=unique_id)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/score", response_model=ScoringResult, tags=["score"])
async def score(req: ScoreRequest) -> ScoringResult:
    if not req.rfp.strip() or not req.proposal.strip():
        raise HTTPException(400, "rfp and proposal are required")
    try:
        return await score_proposal(req.rfp, req.proposal, req.weights)
    except Exception as e:
        log.exception("scoring failed")
        raise HTTPException(500, f"scoring failed: {e}") from e
