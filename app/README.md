# Proposal Scorer — backend

FastAPI backend for the FPT "Proposal Scorer" track, on a **uv** project layout
(`pyproject.toml` + `uv.lock`, package at `src/app/`, `uvicorn app.main:app`). It started from
`../BACKEND.md` (the v0 plan) and then took two rounds of review changes, summarised below.

## Pipeline

```
POST /score/stream {rfp?, proposal, weights?}            (POST /score = same, blocking; POST /rfp/extract = call 1 only)

1. parse        code   → sections with hierarchical ids (§2, §3.1; ¶n fallback)   → event: sections
2. LLM call 1   →  requirements[] + constraints[] + suggestedWeights[]              → event: requirements
3. signals      code   → vague phrases, money & dates in pricing / timeline sections
4. LLM call 2   split (Gemini, default):
                   2a  coverage + constraintViolations          small: ids, enums, one-line fixes  → event: coverage
                   2b  three groups in parallel, findings → scores:
                       understanding  #1 problem, #6 tone         (+ RFP text)
                       commercials    #2 scope, #3 pricing, #4 timeline  (+ regex signals)
                       risk           #7 risk transparency        (+ coverage verdicts)
                merged (local Ollama): one call, coverage → violations → findings → scores
5. grounding    code   → normalise + fuzzy + "is it in the section it claims?"
                   verified / fuzzy (flagged) / unverified (dropped, counted)
                   completeness (#5) computed from coverage; findings de-duplicated across groups
6. aggregate    code   → overall = Σ(score × weight) / Σ(weight); sort by severity   → events: scores, findings, done
```

Every LLM call is cached on disk by `hash(prompt version, model, inputs)`. Weights are in no
key and never reach a model: dragging a slider is step 6 only. Latency in split mode is
`call 1 + 2a + max(2b)`; the same documents are sent to four calls, which is why the merged
mode exists for a single local GPU (`LLM_SPLIT_CALLS=auto` picks by provider).

### Output budget and truncation (why the calls look the way they do)

| Layer | What | Where |
|---|---|---|
| Config | `max_tokens` / `num_predict` explicit and high; `reasoning_effort` low for scoring, medium for coverage; `num_ctx` 16k on Ollama (default 4k silently cut the *prompt*); `finish_reason` checked on every call | `llm.py`, `config.py` |
| Smaller output | coverage carries a quote only for PARTIAL / CONTRADICTED; citations are section ids, not sentences; every quote ≤ 20 words; every free-text field one sentence; completeness never asked of the model | `schema.py`, `prompts.py` |
| Split calls | 2a triage, then three parallel groups each owning a subset of criteria and finding types; per-group failure nulls only that group's criteria | `pipeline.py`, `prompts.GROUPS` |
| Salvage | a cut or malformed answer goes through `json_repair`; if the prefix validates it is used and reported (`meta.truncated`, `warnings`, `partial: true`); otherwise one retry with the problem appended and a strict schema | `llm.call_json` |

### Nothing blanks the screen

| Situation | Result |
|---|---|
| no RFP | call 1 and 2a skipped; coverage empty; completeness `null` with a note; six criteria scored |
| call 1 fails (after retry) | HTTP 502 / SSE `error` — there is nothing worth showing |
| 2a (or the merged call) fails | `done` with `partial: true`, `error`, and the requirements from call 1 |
| a 2b group fails | its criteria `null` with a note; the other groups score; `warnings`, `partial: true` |
| an output is cut | salvaged prefix used; `meta.truncated`, `warnings`, `partial: true`; the cache remembers it |

## Run with Docker (the demo path)

```bash
cp .env.example .env        # then paste your Gemini key into GEMINI_API_KEY
./run.sh up                 # build + start backend, the built frontend and nginx (Gemini; no Ollama)
./run.sh warm               # fill data/cache from the recorded answers: the 4 samples cost nothing
curl localhost/api/health   # {"ok":true}     docs: http://localhost/api/docs
./run.sh score              # weak sample through nginx (blocking)
./run.sh stream response_4_overpromise.md   # same through SSE; watch the events arrive
./run.sh regression         # all 4 samples; asserts weak < medium < strong, overpromise caught
```

Only nginx has a host port: `/api/*` → backend (prefix stripped, buffering off for SSE),
`/` → the built frontend (`../frontend/Dockerfile`, nginx on :3000). The local Ollama service only
starts with `docker compose --profile ollama up` when `LLM_PROVIDER=ollama`.

## Run locally (hot reload)

```bash
uv sync
uv run --env-file .env uvicorn app.main:app --reload   # :8000/docs, Gemini via .env
# offline instead: LLM_PROVIDER=ollama in .env, then
# docker compose up -d ollama && docker compose exec ollama ollama pull qwen2.5:7b
# OLLAMA_URL=http://localhost:11434 uv run --env-file .env uvicorn app.main:app --reload
uv run pytest                 # offline tests (fake provider; no LLM needed)
uv run ruff check . && uv run ruff format --check . && uv run basedpyright
uv run --env-file .env python tests/regression.py    # needs a reachable LLM
```

## LLM provider

Gemini is the default, through the `google-genai` SDK: `GEMINI_MODEL=gemini-3.8-flash` is
built in and only `GEMINI_API_KEY` needs filling in `.env`. Each call sends the Pydantic
schema as the response JSON schema and `LLM_REASONING_EFFORT` as the thinking level (Gemini
2.5 models get the matching token budget). Split mode is on for Gemini: one scoring run is
**5 LLM calls** (1 + 2a + 3) instead of 2. On a free tier, check requests-per-minute before
demoing two uncached documents back to back; `LLM_SPLIT_CALLS=false` forces the merged call.
To run offline set `LLM_PROVIDER=ollama` (see "Run locally").

Every real call appends a row to `data/usage.csv` (time, call, model, prompt / output /
thinking / cached tokens, USD at Gemini 3.8 Flash list price); once a day's total passes
$20 the backend logs a warning, which is what a runaway loop looks like. Rate-limit (429)
and overload (503) responses are retried up to three times with backoff before a run fails.
A hard stop: once the ledger totals `LLM_BUDGET_USD` (5 in `.env.example`) no real call is made;
cache hits keep working. `python -m app.usage` prints today / total / budget.

**Logs.** Every run logs one line per stage and per model call, tagged with a run id: cache
hit or miss, duration, tokens and cost, grounding counts, the overall. Follow them with
`docker compose logs -f backend` (or the uvicorn terminal); `LOG_LEVEL=DEBUG` adds the head of
each prompt and answer. The same notes stream to the UI as `progress` frames, so the run
trace narrates what the model is doing inside each stage.

**Recording and replay.** `LLM_PROVIDER=replay` (see `.env.replay`) answers every prompt from
`tests/fixtures/replay/<sha16>.json`, keyed by the prompt text, and fails loudly on a miss —
no key, no network, no cost. `uv run --env-file .env python tests/record_fixtures.py` records
the four samples plus a no-RFP run through Gemini (only prompts without a recording are paid
for) and writes the full results to `../frontend/src/api/fixtures/results/`. `LLM_REPLAY_FAIL=coverage`
(or `group:<id>`, `extract`) makes a call kind answer invalid JSON to rehearse the degraded
paths; `LLM_REPLAY_DELAY_MS` slows replay down to watch the run trace. `./run.sh warm` and
`make warm` fill `data/cache` from the recordings with the same keys a live run uses.

## Contract

`app/openapi.json` is the wire contract, exported from the app (`uv run python -m
app.openapi_export`; `--check` and `tests/test_openapi.py` fail when it is stale). It carries
the six SSE frames as a `StreamEvent` union on `POST /score/stream`, the 400 / 502 bodies,
and `POST /rfp/extract` (call 1 alone, sharing the cache with a full run). The frontend
generates its types and zod schemas from it (`cd ../frontend && npm run api:gen`). Section
ids in every location field are the ones listed in the `sections` frame, so the UI can
resolve `§4` to "Pricing"; every quote is verbatim after normalisation, so the UI can mark it.

## Layout

| what                  | where                              |
|-----------------------|------------------------------------|
| routes + SSE          | `src/app/main.py`                  |
| pipeline (events, split / merged) | `src/app/pipeline.py`  |
| prompts, groups, rubric (+ version) | `src/app/prompts.py` |
| models (wire + LLM)   | `src/app/schema.py`                |
| section parsing       | `src/app/splitter.py`              |
| quote verification    | `src/app/grounding.py`, `normalize.py` |
| regex signals         | `src/app/signals.py`               |
| weights, completeness, dedupe | `src/app/aggregate.py`     |
| provider, budget, salvage, retry | `src/app/llm.py`        |
| per-call token log, spend ceiling | `src/app/usage.py`      |
| LLM cache (git-ignored) | `data/cache/`                    |
| sample data           | `../sample_data/*.md` (mounted at `/sample_data` in the container) |
