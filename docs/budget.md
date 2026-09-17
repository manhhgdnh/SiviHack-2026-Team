# Spend ledger (USD 5.00 cap on live model calls)

The backend refuses a real call once `app/data/usage.csv` on the key machine totals
`LLM_BUDGET_USD` (5 in `app/.env`). `make spend` prints today / total / budget.

Assumption: about 2k prompt tokens and 2.5k output-plus-thinking tokens per call, about
USD 0.011; a five-call run about USD 0.06.

| # | Step | Mode | Calls | Est. USD | Running | Actual |
|---|---|---|---|---|---|---|
| 1 | Key sanity check (a bad key fails on the first call at USD 0) | live | 0–1 | 0.00 | 0.00 | 0.000 |
| 2 | First recording (`tests/record_fixtures.py`): 4 samples + no-RFP | live | 20 | 0.45 | 0.45 | 0.095 |
| 3 | pytest, the browser protocol in replay mode, screenshots, mock mode | replay | 0 | 0.00 | 0.45 | 0.000 |
| 4 | Prompt-tuning iteration 1 (only changed prompts re-record) | live | ≤ 20 | ≤ 0.45 | 0.90 | not needed |
| 5 | Prompt-tuning iteration 2 | live | ≤ 20 | ≤ 0.45 | 1.35 | not needed |
| 6 | Warm the demo cache from the recordings (`make warm` / `./run.sh warm`) | replay | 0 | 0.00 | 1.35 | 0.000 |
| 7 | Live UI check of the four samples and no-RFP (cache hits after step 6) | cached | 0 | 0.00 | 1.35 | 0.000 |
| 8 | Unseen-pair rehearsal (`docs/rehearsal/`, Harborview) through the compose stack | live | 5 | 0.35 | 1.70 | 0.029 |
| 9 | Compose smoke with a cached sample | cached | 0 | 0.00 | 1.70 | 0.000 |
| 10 | Demo-day tech check, rehearsal pair once through http://localhost | live | 5 | 0.20 | 1.90 | |
| 11 | Demo: judges' pair, one edit re-run, one spare document | live | ~14 | 0.55 | 2.45 | |
| — | Reserve for 429 retries, a third tuning pass, mistakes; the guard stops everything at 5.00 | | | 2.55 | 5.00 | |

The first recording passed the regression criteria on the first attempt (weak 1.14 <
medium 2.29 < strong 4.57; the overpromising sample has one constraint violation, one
contradicted requirement and three findings; the strong one has no violation), so the two
tuning passes were not spent.

Re-recording rules: a change to any prompt wording, a sample file or the canonical text rule
changes the replay keys of the affected calls only; run the recorder again and only those are
paid for. Bump `PROMPT_VERSION` whenever prompts change so the disk cache also refreshes.

Spent so far: USD 0.125 (recording 0.095, unseen-pair rehearsal 0.029). The rehearsal pair
scored 2.0 "Not ready" with the planted violation caught ("no replacement of Koha" against
"we will migrate patron records out of Koha"), one contradicted requirement, two not found,
and fixes on every entry; `docs/screenshots/12-live-rehearsal.jpg`.
