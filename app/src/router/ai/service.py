import hashlib
import time

from pydantic import ValidationError

from .adapter import to_frontend
from .errors import ReviewError
from .extractor import extract_requirements
from .prompts import PROMPT_VERSION
from .provider import GeminiProvider
from .reviewer import review_proposal
from .schemas import ReviewInput, ReviewResponse


class ProposalService:
    def __init__(self, provider=None):
        self.provider = provider

    def review(self, request: ReviewInput | dict) -> ReviewResponse:
        try:
            request = ReviewInput.model_validate(request)
        except ValidationError as exc:
            raise ReviewError(
                "invalid_input",
                "Provide both documents and valid weights for the seven FPT criteria.",
            ) from exc
        provider = self.provider or GeminiProvider()
        start = time.monotonic()
        try:
            extraction = extract_requirements(provider, request.rfp)
            review = review_proposal(provider, extraction, request.rfp, request.proposal)
            return to_frontend(
                extraction,
                review,
                request,
                {
                    "model": provider.model,
                    "prompt_version": PROMPT_VERSION,
                    "elapsed_seconds": round(time.monotonic() - start, 3),
                    "rfp_sha256": hashlib.sha256(request.rfp.encode()).hexdigest(),
                    "proposal_sha256": hashlib.sha256(request.proposal.encode()).hexdigest(),
                    "score_scale": "weighted mean 1–5; overall_100 = unrounded mean × 20, not probability",
                    "weights_policy": "application settings; all seven criteria still evaluated",
                    "human_review_required": True,
                },
            )
        except ValidationError as exc:
            raise ReviewError(
                "invalid_model_output",
                "The review failed validation; no result was accepted.",
                502,
                True,
            ) from exc
        finally:
            if self.provider is None:
                provider.close()
