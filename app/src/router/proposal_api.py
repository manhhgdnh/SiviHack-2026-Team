"""Minimal API runnable without the unrelated classifier/DB/Ollama services."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from router.ai.errors import ReviewError
from router.ai.schemas import ReviewInput, ReviewResponse
from router.ai.service import ProposalService

router = APIRouter(tags=["proposal-review"])


def get_service() -> ProposalService:
    return ProposalService()


@router.post("/api/review", response_model=ReviewResponse)
def review(
    body: ReviewInput, service: Annotated[ProposalService, Depends(get_service)]
) -> ReviewResponse:
    return service.review(body)


def configure_proposal_api(app: FastAPI):
    origins = [
        s.strip()
        for s in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if s.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)

    @app.exception_handler(ReviewError)
    async def review_error(_request, exc: ReviewError):
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def input_error(_request, _exc):
        return JSONResponse(
            status_code=422,
            content=ReviewError(
                "invalid_input",
                "Provide non-empty documents (maximum 100,000 characters each) and valid seven-criterion weights.",
            ).payload(),
        )

    @app.exception_handler(Exception)
    async def internal_error(_request, _exc):
        return JSONResponse(
            status_code=500,
            content=ReviewError(
                "internal_error",
                "The review could not be completed. Please retry or contact the team.",
                500,
            ).payload(),
        )


app = FastAPI(title="Proposal Scorer", version="1.0")
configure_proposal_api(app)


@app.get("/health")
def health():
    return {
        "ok": True,
        "model_configured": bool(os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_MODEL")),
    }
