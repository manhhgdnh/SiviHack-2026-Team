# Proposal Scorer

Reads a draft proposal against the client's RFP and shows where it falls short, with the
passage behind every judgment so a reviewer can check the call rather than trust a number.
SiviHack 2026, Track 1 (FPT Software Europe).

## 1. What the product is

A reviewer for sales proposals, not a writer of them. Paste or upload the client's RFP and the
draft proposal (Markdown or plain text), press **Run review**, and watch the review arrive
stage by stage:

- **Seven criteria scored 1–5** (Appendix A of the brief: problem understanding, scope and
  deliverables, pricing, timeline, completeness vs RFP, tone, risk transparency), each with a
  one-sentence weakness and, where earned, a strength. The overall is a weighted mean computed
  in code; the weight sliders recompute it instantly without a model call.
- **Requirement coverage table** derived from the RFP: every explicit ask marked addressed,
  partial, not found or contradicted, with the RFP passage and the answering proposal passage.
- **Constraint violations kept apart from risk findings**: a proposal that crosses a hard
  client limit (budget, deadline, excluded technology, a system the client said to keep) is
  called out under the verdict, not buried in a list.
- **Every finding points at an exact location**: section id, a verbatim quote verified by
  code against the source text, and a suggested fix that can be previewed and applied to the
  draft, then re-run.
- **Works without an RFP**: the draft is scored on six criteria and the coverage stage is
  skipped, with the omission stated on screen.
- **AI-suggested weights from the RFP**, which the user accepts or adjusts.

## 2. Setup and how to run the demo

Docker path (the demo):

```bash
cp app/.env.example app/.env        # then paste GEMINI_API_KEY into app/.env
cd app && docker compose up -d --build
./run.sh warm                       # fill the cache from the recorded answers, no model call
open http://localhost               # the app; the API is under /api (docs at /api/docs)
```

Dev path (hot reload):

```bash
cd app && uv sync && uv run --env-file .env uvicorn app.main:app --reload --port 8000
cd frontend && npm ci && VITE_API_URL=/api npm run dev      # http://localhost:5173
```

Offline paths: `uv run --env-file .env.replay uvicorn app.main:app` serves the recorded
Gemini answers for the sample set with no key and no cost; `npm run dev` without
`VITE_API_URL` runs the frontend alone on the recorded results.

Checks: `make check` (backend tests, lint, type checks, frontend build). The manual browser
protocol is in `docs/verification.md`; the spend ledger in `docs/budget.md`.

Demo script (5 minutes): the problem (manual, inconsistent review) → load the weak sample
and run → point at one finding, its quote and its fix → drag a weight slider → load the
overpromising sample and show the constraint violation → invite the judge to paste their own
pair. The four samples are served from the cache; the judges' pair is scored live.

## 3. Tech used

- Backend: Python 3.13, FastAPI (native Server-Sent Events), Pydantic v2, `google-genai`
  with Gemini 3.8 Flash, rapidfuzz and json-repair for grounding and salvage; uv, pytest,
  ruff, basedpyright.
- Frontend: React 19, Vite 8, TypeScript, Tailwind v4, shadcn/ui, TanStack Query
  (streamed query), react-markdown; types and zod schemas generated from the backend's
  OpenAPI document with `@hey-api/openapi-ts`; oxlint.
- Deployment: Docker Compose with nginx in front (`/api/*` → backend, `/` → the built app).
- Architecture: one extraction call on the RFP (cached by its text), then a coverage call and
  three parallel scoring groups; a grounding pass verifies every quote and section; the
  completeness score and the overall are computed in code; a disk cache and a replay provider
  make repeated runs and tests free.

## 4. Dataset, API, libraries and template used

- Dataset: `sample_data/` (the sponsor's fictional NordFrame RFP, four responses and a scoring
  example). No real client data.
- API: the Google Gemini API through the official `google-genai` SDK. No other external service.
- Python libraries: `requirements.txt` (generated from `app/pyproject.toml` and `uv.lock`).
- JavaScript libraries: `frontend/package.json`.
- Template: the Vite `react-ts` template with shadcn/ui components.
- Recorded model answers for tests and the offline demo: `app/tests/fixtures/replay`
  (keyed by prompt) and `frontend/src/api/fixtures/results` (full results per sample).

Everything the pitch claims is in this repository: grounded quotes in
`app/src/app/grounding.py`; constraint violations in `app/src/app/schema.py` and
`app/src/app/prompts.py`; split calls and the cache in `app/src/app/pipeline.py`; weights in
code in `app/src/app/aggregate.py` and `frontend/src/lib/score.ts`; streaming in
`app/src/app/main.py` and `frontend/src/api/stream.ts`; recorded fixtures in
`app/src/app/replay.py`.

## 5. Current limitations

- Markdown and plain text only; no PDF or PowerPoint import.
- English prompts and rubric.
- Five model calls per review (about 5–20 seconds and about USD 0.06 on Gemini 3.8 Flash);
  a free-tier key can hit its per-minute limit when two people run at once.
- Quotes are at most 20 words and are dropped when the model paraphrases (the count is in
  `meta.ungroundedDropped`); a near match is shown with a "≈" mark.
- Completeness is derived from coverage, not judged by the model.
- No authentication and no persistence beyond the on-disk cache; one RFP per run.
- Suggested weights are a heuristic read of the RFP, not a calibrated model.
- In the demo the four samples answer from the cache; only an unseen pair reaches the model.
