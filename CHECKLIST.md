# Checklist

Pulled from three sources: Track 1 (sections 5, 7, 8), the handbook (submission deadline, README, pitch format, rubric 1.1–1.6) and what we've discussed. Grouped by priority so you know what to cut when time runs out.

## A. Must have — missing any of these costs points immediately

**Product**
- [ ] Input RFP + proposal by both pasting text and uploading `.md` files. The judges will bring an unseen Markdown pair to test live.
- [ ] Works without an RFP (empty requirements, criterion #5 returns null with a note), since you can't be sure the judge pastes both.
- [ ] Results appear during the demo, no blank screen: staged spinner or SSE, and `partial: true` if call 2 fails.
- [ ] Every finding points to an exact location: `section_id` + grounded quote, with a `suggested_fix`. This is FPT's judging criterion 1.
- [ ] Requirement coverage table derived from the RFP (covered / partial / missing / contradicted). This is judging criterion 2.
- [ ] `constraint_violations` kept separate from risks, so `response_4_overpromise` gets caught for the right reason.
- [ ] Score 1–5 on the 7 Appendix A criteria + one-sentence comment each, overall computed in code.
- [ ] Verified on the 4 samples: weak < medium < strong, overpromise has ≥ 1 violation. Screenshot the results for the slides.

**Submission (deadline 15:00 on 18.09, nothing can be edited after)**
- [ ] GitHub repo, access set as the organizers require.
- [ ] README with exactly the 5 items the handbook asks for: what the product is · setup and how to run the demo · tech used · dataset/API/library/template used + `requirements.txt` · current limitations.
- [ ] Presentation slides.
- [ ] Code matches what the pitch claims. Technical Assistants use AI to review the codebase against the presentation, so don't describe features that aren't in the repo.

## B. Should have — earns points on 1.4, 1.5, 1.6

- [ ] Configurable criteria: weight sliders recompute in code without an LLM call (say so in the pitch); adding/removing a criterion triggers call 2 again.
- [ ] AI suggests weights from the RFP (`suggested_weights` in call 1), user accepts or adjusts.
- [ ] FAR severity labels: Deficiency / Significant weakness / Weakness / Strength, findings sorted by that.
- [ ] Code-derived signals shown as evidence (vague phrases, amounts, dates) next to the Pricing/Timeline scores.
- [ ] A "Red Team view" tab: strengths / weaknesses / risks from the evaluator's angle, named after Shipley in the UI.
- [ ] Criterion #6 backed by a we/you ratio signal and boilerplate detection.

## C. If time remains — bonus

- [ ] PDF upload (PyMuPDF → text → paragraph fallback). FPT's bonus criterion, about 30 minutes.
- [ ] Export results to Markdown/PDF to hand to the proposal writer.
- [ ] Scoring history within a session to compare before/after edits.

## D. Pitch day (16:00 on 18.09)

- [ ] Morning tech check: plug into the projector, then change nothing on the machine.
- [ ] Demo partly works offline: pre-cache results for the 4 samples so there's something to click if the wifi drops; only the judges' secret pair hits the real API.
- [ ] Enough API credit left for the demo. Stop batch testing from the evening of 17.09.
- [ ] 5-minute script: the problem (manual, inconsistent review) → paste `response_1_weak` → point at one specific finding + fix → drag a slider → invite the judge to paste their file. No more than 90 seconds of talking without a demo on screen.
- [ ] Q&A roles: one person on architecture/LLM, one on the rubric and the Shipley/FAR sources, one on business value.
- [ ] Slides include: the 2-call + cache architecture, why reasons-not-ranking, known limitations (better said upfront than asked about).

If group A isn't done by noon on 18.09, drop group C entirely and keep only the first two items of group B.
