"""Generate an explicit synthetic fixture using validated, human-authored stubs."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import DATA, StubProvider  # noqa: E402

from router.ai.schemas import ReviewInput, ReviewResponse  # noqa: E402
from router.ai.service import ProposalService  # noqa: E402

request = {
    "rfp": (DATA / "synthetic_rfp.md").read_text(),
    "proposal": (DATA / "synthetic_proposal.md").read_text(),
}
result = ProposalService(StubProvider()).review(request)
result.metadata["fixture_notice"] = (
    "SYNTHETIC: human-authored provider stubs; not a Gemini evaluation or sponsor score."
)
result.metadata["elapsed_seconds"] = 0.0
out = ROOT / "fixtures"
out.mkdir(exist_ok=True)
(out / "synthetic-review.json").write_text(result.model_dump_json(by_alias=True, indent=2) + "\n")
(out / "synthetic-input.json").write_text(ReviewInput(**request).model_dump_json(indent=2) + "\n")
(out / "review-response.schema.json").write_text(
    __import__("json").dumps(ReviewResponse.model_json_schema(by_alias=True), indent=2) + "\n"
)
