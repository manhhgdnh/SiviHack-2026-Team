# Manual browser protocol

Run this after any change to the frontend, the adapter, the backend contract or the
recordings. Any red step is a bug in one of those. Nothing goes live until every step is
green in replay mode. Labels in quotes are the visible or accessible names on screen.

## E0. Start in replay mode (free)

```bash
# Terminal 1 — backend on the recordings; no key, no cost. Keep the delay to watch the trace.
cd app && LLM_REPLAY_DELAY_MS=1500 uv run --env-file .env.replay uvicorn app.main:app --port 8000
# Terminal 2 — frontend against the backend through the Vite proxy
cd frontend && VITE_API_URL=/api npm run dev
```

Open http://localhost:5173 at 1440×900 with DevTools → Network filtered on `score`. Terminal 1
prints one `POST /score/stream` line per run; that log is the "no request" witness in E7.

## E1. Load and paste

Click "Medium" → both textboxes fill, footers show "N lines · N words", "Run review"
enabled. "Clear the Draft Proposal" → footer "empty", Run disabled. Click "Medium" again,
then "Clear the Request for Proposal" → Run stays enabled and the status line "No RFP
loaded — the draft will be scored on its own." appears (the Run button moves up a little
above it). Click "Medium" to restore.

## E2. Upload for both witnesses

"Upload the Request for Proposal as .md" with `sample_data/rfp_nordframe.md` and "Upload the
Draft Proposal as .md" with `sample_data/response_2_medium.md` → the draft pane shows the
same "33 lines · 195 words" as the sample button does (the `**Variant**` banner is dropped on
upload). "Run review" → a full review with no "no recording" rail. This proves paste, upload
and the sample buttons send identical canonical text.

## E3. Run Medium and watch the trace

Heading "Collating the draft against the RFP"; the list "Run progress" advances one row per
frame: under row 2 the status "10 requirements · 4 constraints" appears before row 3
finishes, under row 3 "2 not found" (or "every requirement addressed"), under row 5 "n
findings"; then the review replaces the trace. With the delay each call visibly steps; no
blank screen at any point. In Network the request is an `eventstream` whose EventStream tab
lists `sections, requirements, coverage, scores, findings, done`.

## E4. The review

Band: a verdict word and "N.N /5" (Medium at untouched shares: 2.3, "Not ready"). Tally
"4 addressed · 4 partial / unclear · 2 not found". "Issues 8": the first "Must fix" entry is
open with "The draft says", "Why it matters" and a "Suggested fix" with Copy / Preview in
draft / Apply to draft / Mark fixed / Not relevant; entries carry chips like "R §2 ·
Requirements" and "P §4 · Pricing"; a finding reads "Scope & Deliverables Clarity · Vague
wording". "Requirements 10": the strip "Asked / Contradicted / Not found / Partial /
Addressed" filters the rows; each row has the requirement's name, the italic RFP quote, a
note (except addressed ones), R and P chips or "no answering passage", and a coloured
square; below the list "Constraints 4" with Technology / Budget / Deadline readings and hollow
"Respected" squares. "Criteria 7": seven rows with N/5, five marks, a percentage and a slider,
a note where there is one ("Computed from coverage…" on Completeness), a strength, a weakness
and chips; one chip on Risk & Assumptions carries "≈" (near match) with a hover title.

## E5. Overpromising: a violation, separate from risks

"Edit the draft" → "Overpromising" → Run. Under the band the alert "The draft conflicts with
the RFP" shows "Violates a client constraint · Constraint · Technology", R asks "no migration
to a new database." and P says "migrating away from your current PostgreSQL database…", with
"Show the violation". "Issues 11": the group "Violates a client constraint 1" sits above "Must
fix 7" with the reading "Constraint · Technology", the "R asks" line, a P chip, "Why it
breaks the constraint" and a fix; the 8-week timeline and scope-creep findings sit below as
findings. The tally shows "1 contradicted". "Show the violation" opens both witnesses with
the RFP's requirement 3 and the draft's "migrating away…" passage marked.

## E6. No RFP

"Edit the draft" → "Medium" → "Clear the Request for Proposal" → Run (the button is above
the status line). Review: "Fix before sending 2.5 /5"; the note "No RFP provided" with "Add
the RFP"; no tally; no R rail; "Requirements 0" with "No client requirements to check
against — no RFP was provided…"; "Criteria 6/7" with "Completeness vs RFP ] —" and "Not
assessable: no RFP provided. Not counted in the overall."

## E7. Weights recompute in code

On Criteria, move a slider (click on its track or focus it and press →). The band's number
and word change immediately (2.3 "Not ready" → 2.6 "Fix before sending" when Completeness
goes to 55 %), the other percentages shrink so the shares still total 100, Terminal 1 prints
no new POST line and Network shows no new request.

## E8. Degraded results

Restart Terminal 1 with `LLM_REPLAY_FAIL=coverage` → Re-run Medium: band in ink "— /5 Not
scored", alert "Review incomplete" with the backend's error text and "Re-run", "Issues 0 —
No issues were assessed.", "Requirements 10" with the lead line "Coverage was not
assessed…" and hollow "not assessed" squares, "Criteria 0/7". Restart with
`LLM_REPLAY_FAIL=group:commercials` → status "Partial review" listing "Scoring group
'commercials' failed…", band scored from the other criteria, "Criteria 4/7"; Scope, Pricing
and Timeline read "—" with "Not assessable: scoring group 'commercials' failed. Not counted
in the overall." Restart with `LLM_REPLAY_FAIL=extract` → Run ends on the setup rail "The
review stopped while reading the documents: … Nothing was saved — press Run review to try
again." Restart Terminal 1 clean.

## E9. Backend down, unseen document

Stop Terminal 1 → Run → within seconds the crimson rail "The review service could not be
reached. Is the backend running? …" (the Vite proxy answers 502 for a dead backend; nginx
does the same), both documents intact. Start it → Run works without a reload. Paste an
unrelated text as the draft → Run → the rail reports the replay miss ("no recording for the
extract prompt…"); in live mode the same action is a real call.

## E10. Suggest weights, apply a fix

Setup with the RFP loaded: "Suggest weights from the RFP" → "Reading the RFP…" → "Read from
the RFP: 10 requirements, 4 constraints. Each reason below cites the passage it came from."
and a reason under each criterion; the budget bar re-proportions. With the RFP empty the
button is greyed with "Paste the RFP first." Run, then "Apply to draft" on the first entry →
"applied to the draft" beside its chips and the banner "The draft has changed since this
review ran…" with "Re-run against the edited draft"; "Revert" removes both.

## E11. Mock mode (no backend)

Restart Terminal 2 as `npm run dev` with no `VITE_API_URL`. "Medium" → Run → the review from
`results/medium.json` with the numbers of E4, the trace paced by the recorded frames. Paste
an unknown document → the "This build replays recorded results…" rail. Restore
`VITE_API_URL=/api` afterwards.

## E12. Compose stack

`cd app && docker compose up -d --build && ./run.sh warm`; `curl -fsS localhost/api/health`
→ `{"ok":true}`; http://localhost serves the built app; "Medium" → Run → Network shows
`/api/score/stream` 200 `text/event-stream` and the `done` payload has `"scoreCached": true`.

## E13. Live mode, once, inside the ledger

Backend with the key (`uv run --env-file .env uvicorn app.main:app --port 8000`, or the
compose stack). The four samples answer from the cache after `make warm` (`meta.scoreCached`
true, USD 0). Paste an unseen pair (`docs/rehearsal/`) → a full review in under a minute with
the trace stepping in real time, at least one finding whose quote marks in the draft, few
dropped quotes. Log `make spend` into `docs/budget.md`.
