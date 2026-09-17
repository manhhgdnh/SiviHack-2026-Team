from pathlib import Path

import pytest

from router.ai.schemas import CRITERIA, ProposalReview, RFPExtraction

DATA = Path(__file__).parent / "data"


@pytest.fixture
def documents():
    return {
        "rfp": (DATA / "synthetic_rfp.md").read_text(),
        "proposal": (DATA / "synthetic_proposal.md").read_text(),
    }


def synthetic_outputs():
    """Human-authored provider stubs, never advertised as Gemini output."""
    quotes = [
        "Patient appointment records must remain in the EU.",
        "Send confirmation emails within five minutes of a booking.",
        "State support response times after launch.",
    ]
    proposal_quotes = [
        "All appointment records will be stored exclusively in the United States.",
        "Confirmation emails will be sent within one minute of a booking.",
        "Support will be available after launch; response targets are to be agreed.",
    ]
    sections = ["Hosting", "Notifications", "Support"]
    extraction = RFPExtraction(
        requirements=[
            {
                "id": f"RFP-{i + 1:03d}",
                "category": section,
                "requirement": quote,
                "mandatory": i == 0,
                "rfp_section": section,
                "rfp_quote": quote,
            }
            for i, (quote, section) in enumerate(zip(quotes, sections, strict=True))
        ]
    )
    review = ProposalReview(
        requirement_assessments=[
            {
                "requirement_id": f"RFP-{i + 1:03d}",
                "status": ["contradicted", "satisfied", "partial_or_unclear"][i],
                "severity": ["high", "low", "medium"][i],
                "explanation": [
                    "US-only storage conflicts with the EU restriction.",
                    "One minute meets the five-minute limit.",
                    "Response times are deferred rather than specified.",
                ][i],
                "rfp_evidence": {"source": "rfp", "section": sections[i], "quote": quotes[i]},
                "proposal_evidence": [
                    {"source": "proposal", "section": sections[i], "quote": proposal_quotes[i]}
                ],
                "suggested_fix": [
                    "Confirm an EU hosting design in Hosting before making a commitment.",
                    None,
                    "Add approved response targets in Support.",
                ][i],
            }
            for i in range(3)
        ],
        criteria=[
            {
                "criterion": name,
                "score": 4,
                "comment": "Synthetic transport fixture; this score is not a model evaluation.",
                "strengths": ["A concrete notification target is stated."],
                "weaknesses": [],
                "evidence": [
                    {"source": "proposal", "section": "Notifications", "quote": proposal_quotes[1]}
                ],
            }
            for name in CRITERIA
        ],
        risks=[],
    )
    return extraction, review


class StubProvider:
    model = "synthetic-stub-not-gemini"

    def __init__(self, extraction=None, review=None):
        base_extract, base_review = synthetic_outputs()
        self.extraction = extraction or base_extract
        self.review = review or base_review
        self.calls = []

    def generate(self, schema, system, payload):
        self.calls.append((schema, system, payload))
        output = self.extraction if schema is RFPExtraction else self.review
        return output.model_copy(deep=True)


@pytest.fixture
def provider():
    return StubProvider()
