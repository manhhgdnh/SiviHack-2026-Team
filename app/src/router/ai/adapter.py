from .grounding import Document
from .schemas import (
    CRITERIA,
    Notification,
    ProposalReview,
    ReviewInput,
    ReviewResponse,
    RFPExtraction,
    UICriterion,
    UIIssue,
    UIRequirement,
)
from .scoring import aggregate

STATUS_MAP = {
    "satisfied": "addressed",
    "partial_or_unclear": "partial",
    "contradicted": "contradicted",
    "not_found": "missing",
}
SEVERITY_MAP = {"critical": "must", "high": "must", "medium": "should", "low": "optional"}
PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def to_frontend(
    extraction: RFPExtraction, review: ProposalReview, request: ReviewInput, metadata: dict
) -> ReviewResponse:
    docs = {"rfp": Document(request.rfp, "rfp"), "proposal": Document(request.proposal, "proposal")}
    by_id = {a.requirement_id: a for a in review.requirement_assessments}
    rows, issues, notifications, actions = [], [], [], []
    for n, req in enumerate(extraction.requirements, 1):
        a = by_id[req.id]
        source = docs["rfp"].citation(a.rfp_evidence)
        answered = (
            docs["proposal"].citation(a.proposal_evidence[0]) if a.proposal_evidence else None
        )
        anchor = f"requirement-{req.id}"
        rows.append(
            UIRequirement(
                id=req.id,
                ref=str(n),
                section=source.section,
                text=req.requirement,
                status=STATUS_MAP[a.status],
                answeredAt=answered,
                source=source,
                note=a.explanation,
                severity=a.severity,
                mandatory=req.mandatory,
                suggestedFix=a.suggested_fix,
                anchor_id=anchor,
                rfp_evidence=a.rfp_evidence,
                proposal_evidence=a.proposal_evidence,
            )
        )
        if a.status == "contradicted":
            notifications.append(
                Notification(
                    requirement_id=req.id,
                    severity=a.severity,
                    message=a.explanation,
                    anchor_id=anchor,
                )
            )
        if a.status != "satisfied":
            issues.append(
                UIIssue(
                    id=f"issue-{req.id}",
                    ref=str(len(issues) + 1),
                    severity=SEVERITY_MAP[a.severity],
                    criterionId="c-completeness",
                    lemma=req.requirement,
                    quoted=a.proposal_evidence[0].quote if a.proposal_evidence else None,
                    # An absent passage cannot have a fabricated proposal location.
                    location=answered or source,
                    against=source if answered else None,
                    whyItMatters=a.explanation,
                    suggestedFix=a.suggested_fix,
                )
            )
            actions.append((PRIORITY[a.severity], n, f"{req.id}: {a.suggested_fix}"))
    for i, risk in enumerate(review.risks, 1):
        proposal_evidence = next(e for e in risk.evidence if e.source == "proposal")
        rfp_evidence = next((e for e in risk.evidence if e.source == "rfp"), None)
        issues.append(
            UIIssue(
                id=f"risk-{i}",
                ref=str(len(issues) + 1),
                severity=SEVERITY_MAP[risk.severity],
                criterionId=CRITERIA[risk.criterion],
                lemma=risk.explanation,
                quoted=proposal_evidence.quote,
                location=docs["proposal"].citation(proposal_evidence),
                against=docs["rfp"].citation(rfp_evidence) if rfp_evidence else None,
                whyItMatters=risk.explanation,
                suggestedFix=risk.suggested_fix,
            )
        )
        actions.append((PRIORITY[risk.severity], len(rows) + i, risk.suggested_fix))
    for c in review.criteria:
        if c.suggested_fix:
            primary = next((e for e in c.evidence if e.source == "proposal"), c.evidence[0])
            against = next((e for e in c.evidence if e.source == "rfp"), None)
            issues.append(
                UIIssue(
                    id=f"criterion-{c.criterion}",
                    ref=str(len(issues) + 1),
                    severity="must" if c.score <= 2 else "should",
                    criterionId=CRITERIA[c.criterion],
                    lemma=c.comment,
                    quoted=primary.quote if primary.source == "proposal" else None,
                    location=docs[primary.source].citation(primary),
                    against=docs["rfp"].citation(against)
                    if against and primary.source != "rfp"
                    else None,
                    whyItMatters=" ".join(c.weaknesses) or c.comment,
                    suggestedFix=c.suggested_fix,
                )
            )
            actions.append((1 if c.score <= 2 else 2, len(rows) + len(issues), c.suggested_fix))
    criteria = [
        UICriterion(
            criterionId=CRITERIA[c.criterion],
            score=c.score,
            strength=" ".join(c.strengths) or None,
            weakness=" ".join(c.weaknesses) or c.comment,
            comment=c.comment,
            citations=[docs[e.source].citation(e) for e in c.evidence],
        )
        for c in sorted(review.criteria, key=lambda c: list(CRITERIA).index(c.criterion))
    ]
    actions.sort(key=lambda a: (a[0], a[1]))
    return ReviewResponse(
        requirements=rows,
        issues=issues,
        criteria=criteria,
        notifications=notifications,
        top_actions=[a[2] for a in actions[:5]],
        review=review,
        metadata=metadata,
        **aggregate(review, request.criteria),
    )
