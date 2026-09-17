from .errors import ReviewError
from .grounding import Document
from .prompts import REVIEW_SYSTEM
from .schemas import ProposalReview, RFPExtraction


def review_proposal(provider, extraction: RFPExtraction, rfp: str, proposal: str) -> ProposalReview:
    output = provider.generate(
        ProposalReview,
        REVIEW_SYSTEM,
        {
            "rfp": rfp,
            "requirements": extraction.model_dump()["requirements"],
            "proposal": proposal,
        },
    )
    output = ProposalReview.model_validate(output.model_dump())
    requirements = {r.id: r for r in extraction.requirements}
    if {a.requirement_id for a in output.requirement_assessments} != set(requirements):
        raise ReviewError(
            "incomplete_assessments",
            "The review must assess every extracted requirement exactly once.",
            502,
        )
    docs = {"rfp": Document(rfp, "rfp"), "proposal": Document(proposal, "proposal")}
    for assessment in output.requirement_assessments:
        req = requirements[assessment.requirement_id]
        assessment.rfp_evidence = docs["rfp"].ground(assessment.rfp_evidence)
        if assessment.rfp_evidence.quote != req.rfp_quote:
            raise ReviewError(
                "mismatched_evidence", "An assessment references a different RFP obligation.", 502
            )
        assessment.proposal_evidence = [
            docs["proposal"].ground(e) for e in assessment.proposal_evidence
        ]
        # A model cannot lower the priority of a binding contradiction or hide it via score weights.
        if assessment.status == "contradicted":
            assessment.severity = "critical" if req.mandatory else "high"
        elif assessment.status == "not_found" and req.mandatory:
            assessment.severity = "critical"
        elif assessment.status == "satisfied":
            assessment.severity = "low"
            assessment.suggested_fix = None
    for item in [*output.criteria, *output.risks]:
        item.evidence = [docs[e.source].ground(e) for e in item.evidence]
    return output
