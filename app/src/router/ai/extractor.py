from .grounding import Document
from .prompts import EXTRACT_SYSTEM
from .schemas import Evidence, RFPExtraction


def extract_requirements(provider, rfp: str) -> RFPExtraction:
    output = provider.generate(RFPExtraction, EXTRACT_SYSTEM, {"rfp": rfp})
    # Revalidate even when using an injected provider.
    output = RFPExtraction.model_validate(output.model_dump())
    document = Document(rfp, "rfp")
    ordered = []
    for index, req in enumerate(output.requirements):
        evidence = document.ground(
            Evidence(source="rfp", section=req.rfp_section, quote=req.rfp_quote)
        )
        span = document.locate(evidence.quote, evidence.section)
        ordered.append(
            (
                span.start,
                index,
                req.model_copy(
                    update={
                        "rfp_quote": evidence.quote,
                        "rfp_section": evidence.section,
                    }
                ),
            )
        )
    ordered.sort(key=lambda item: (item[0], item[1]))
    return RFPExtraction(
        requirements=[
            req.model_copy(update={"id": f"RFP-{i:03d}"})
            for i, (_, _, req) in enumerate(ordered, 1)
        ]
    )
