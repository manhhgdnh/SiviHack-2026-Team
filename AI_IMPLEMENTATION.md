# Proposal Scorer AI handoff

Implemented for SiviHack Track 1, FPT Software Europe. The uploaded Track 1 PDF and
its Appendix A take priority over planning notes. The sponsor's example specifies
useful behavior, not exact target scores. No ISO/APMP certification is claimed.

## Inspected baseline

Baseline commit: `82f1149e56c5cebb39e0719bd45cd633fe93f32b`.

| Existing area | Finding / integration decision |
|---|---|
| `frontend/` | React 19, Vite 8, TypeScript, Tailwind, TanStack Query. Preserved. |
| `frontend/src/api/client.ts` | Previously matched the proposal to four exact samples and returned `REVIEWS`. Now calls the API by default. |
| `frontend/src/api/schema.ts` | Existing `Review`/`Requirement`/`Issue` contract and 1-indexed line citations retained, with additive metadata. |
| `frontend/src/features/review/apparatus.tsx` | Requirements, status counters, criteria scores, evidence and suggested fixes. |
| `frontend/src/features/review/review-view.tsx` | Result layout, source panes, priority issues; now includes contradiction alerts and readiness reasons. |
| `frontend/src/components/apparatus/citation-ref.tsx` | Existing source navigation reused. |
| `app/src/router/` | FastAPI starter for an unrelated Ollama task classifier; no proposal review implementation existed. |
| `BACKEND.md` | Planning document, not implemented backend. Extraction/reviewer ideas reused and strengthened. No `prompt_engineer.md` file was present in this checkout. |
| `sample_data/` | Sponsor Markdown RFP, four proposals, scoring example. Runtime does not import these. |

## Architecture and files

Two sequential model calls, with deterministic validation and assembly between/after them:

1. Original RFP → Gemini requirement extraction → Pydantic + verified source quotes
   → IDs assigned in source order.
2. Original RFP + validated requirements + original proposal → Gemini review
   → Pydantic + requirement coverage checks + quote grounding.
3. Python computes counters, seven-criterion weighted mean, readiness gates,
   contradiction notifications, anchors and the compatible frontend result.

| File / area | Responsibility |
|---|---|
| `app/src/router/ai/schemas.py` | Strict internal schemas and typed API response. |
| `app/src/router/ai/prompts.py` | Versioned extraction/reviewer instructions and seven FPT criteria. |
| `app/src/router/ai/provider.py` | `google-genai` structured output, timeout, safe API errors; no automatic hidden retry. |
| `app/src/router/ai/extractor.py` | Quote validation and source-order IDs. |
| `app/src/router/ai/reviewer.py` | Exactly one assessment per requirement; verified evidence and severity floors. |
| `app/src/router/ai/grounding.py` | Source quotes, headings and inclusive line references. |
| `app/src/router/ai/scoring.py` | Configurable readiness policy and aggregation. |
| `app/src/router/ai/adapter.py` | Internal semantics → existing UI vocabulary, issues, notifications, actions. |
| `app/src/router/ai/service.py` | Pipeline orchestration, input hashes and metadata. |
| `app/src/router/ai/errors.py`, `__main__.py`, `__init__.py` | Safe errors, CLI and package entrypoint. |
| `app/src/router/proposal_api.py` | Standalone FastAPI entrypoint and reusable router. |
| `app/src/router/main.py` | Mounts the same router in existing app; lazy imports retain legacy endpoints. |
| `app/requirements-ai*.txt`, `.env.example`, `pyproject.toml`, `uv.lock` | Minimal install and existing project dependency integration. |
| `app/tests/`, `app/pytest.ini` | Failure/contract/scoring/grounding/SDK tests; synthetic documents. |
| `app/scripts/evaluate_samples.py` | Explicit live evaluation on four sponsor samples plus synthetic pair. |
| `app/scripts/make_fixture.py`, `app/fixtures/` | Reproducible synthetic input/output and complete JSON schema. |
| `frontend/src/api/client.ts`, `schema.ts`, `.env.example` | Real request seam, safe errors, additive response types. |
| `frontend/src/App.tsx` | Uses server score/readiness; exposes rerun errors instead of silently showing stale success. |
| `frontend/src/features/review/{apparatus,criteria-setup,review-view,run-trace}.tsx` | Compatible source UI, alerts, honest loading state and action-only fixes. |

No agents, RAG, embeddings, vector database, new database or frontend framework.
Markdown core only; PDF/PPT ingestion is not implemented.

## Exact API contract

`POST /api/review`, JSON body:

```json
{
  "rfp": "# RFP\n...",
  "proposal": "# Draft\n...",
  "criteria": [
    {"id": "c-problem", "name": "Problem Understanding", "whatToCheck": "", "enabled": true, "weight": 1},
    {"id": "c-scope", "enabled": true, "weight": 1},
    {"id": "c-pricing", "enabled": true, "weight": 1},
    {"id": "c-timeline", "enabled": true, "weight": 1},
    {"id": "c-completeness", "enabled": true, "weight": 1},
    {"id": "c-tone", "enabled": true, "weight": 1},
    {"id": "c-risk", "enabled": true, "weight": 1}
  ]
}
```

`criteria` may be omitted or null for equal weights. Explicit settings are the
entire enabled weighting configuration, not partial overrides. Weights need not
sum to 100; the backend normalizes by their sum. Negative, nonfinite, duplicate,
unknown/custom or all-zero enabled configurations are rejected. All seven official
criteria are always evaluated; disabling their aggregate weight cannot hide a
material issue. UI weighting can be adjusted before running; after review, edit
settings and rerun rather than locally recomputing a potentially unsafe verdict.

| Internal status | Existing UI status | Display |
|---|---|---|
| `satisfied` | `addressed` | Green |
| `partial_or_unclear` | `partial` | Amber |
| `contradicted` | `contradicted` | Red |
| `not_found` | `missing` | Grey |

The response preserves `verdict`, `overall`, `criteria`, `requirements`, `issues`.
Added fields: `schema_version`, `overall_100`, `readiness`, `readiness_reasons`,
`counters`, `notifications`, `top_actions`, canonical `review` and `metadata`.
Each requirement includes severity, mandatory flag, suggested action, exact RFP
and proposal evidence, and a `requirement-RFP-001` style anchor.

Complete, machine-readable contract: `app/fixtures/review-response.schema.json`.
Working input and response: `app/fixtures/synthetic-input.json` and
`app/fixtures/synthetic-review.json`. **These are explicitly human-authored
synthetic provider fixtures, not Gemini output or sponsor quality scores.**

`Citation = {witness: "R"|"P", section: string, from: number, to: number}` uses
1-indexed inclusive lines of the submitted original text. Missing proposal evidence
has `answeredAt: null` and an empty evidence list; an issue may reference the RFP
as its location. It never fabricates a proposal passage for an absence.

Error response (HTTP 422 / 502 / 503 / 504, unexpected internal error 500):

```json
{"error":{"code":"model_timeout","message":"The model timed out. Please retry.","retryable":true}}
```

The UI shows these failures and never silently substitutes sample results.

## Scoring and gates

`overall = round(sum(weight × score) / sum(weight), 1)` on a 1–5 scale.
`overall_100 = round(unrounded_mean × 20, 1)` (20–100, **not** a probability).
The retained UI default weights are 15/15/14/14/14/14/14; omitted API settings use
equal weights. These are prototype settings, not an international standard.

`ReadinessPolicy` in `scoring.py` exposes the thresholds. Binding contradictions
are elevated to critical and force `not_ready`, even with an 80/100 aggregate.
Missing mandatory requirements are critical and force at least `major_revision`.
Any explicit contradiction, two high/critical issues, or serious criterion gaps
prevent a `ready` result. Legacy UI verdicts map `minor_revision` and
`major_revision` to `fix`; the detailed readiness and reasons remain visible.
A human decides whether the proposal is actually ready to send.

## Run locally

Minimal standalone environment (Python 3.12+; existing full project pins 3.13):

```bash
cd app
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-ai-dev.txt
cp .env.example .env
```

Set `.env` locally:

```dotenv
GEMINI_API_KEY=your-local-key
GEMINI_MODEL=your-available-structured-output-model
GEMINI_TIMEOUT_MS=90000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

No model ID is assumed available to your sponsor account. Never put the API key
in frontend variables or commit `.env`.

```bash
# API; reads app/.env. No Ollama, database or n8n required.
python -m uvicorn router.proposal_api:app --app-dir src --env-file .env --port 8000
```

Existing full project route is also supported after `uv sync`:
`uv run uvicorn router.main:app --env-file .env --port 8000`.
The Docker configuration already launches this entrypoint and uses the updated lock.

Frontend, second terminal:

```bash
cd frontend
npm ci
# .env.local: VITE_API_URL=http://localhost:8000/api
npm run dev
```

`VITE_REVIEW_MODE=live` is the default; `fixture` explicitly enables the old four
sample findings. No key is needed for fixture mode. The loading view labels it.
AI-inferred weight suggestions and custom criteria were mocked in the baseline;
this MVP offers an honest equal-weight reset and disables adding custom criteria.

CLI from `app/` (set `PYTHONPATH=src`; in PowerShell use `$env:PYTHONPATH="src"`):

```bash
PYTHONPATH=src python -m router.ai ../sample_data/rfp_nordframe.md ../sample_data/response_1_weak.md --output evaluation-output/weak.json
```

## Tests and evaluation

```bash
cd app
python -m pytest -q tests
PYTHONPATH=src python scripts/make_fixture.py
PYTHONPATH=src python scripts/evaluate_samples.py --live
```

Live evaluation uses only the original documents, removes test variant labels
from proposals to prevent label leakage, saves every accepted JSON result and a
report under `evaluation-output/`. It exits nonzero if cases fail, need review,
or are not run. Qualitative checks are test-only expectations and do not enter
runtime prompts/scoring. Read the actual matrix/evidence before trusting a pass.

Verified in the implementation environment:

- 54 offline tests passed: validation failures, missing/duplicate IDs, quote/section
  grounding, four-sample citation roundtrips, aggregation/gates, prompt data boundary,
  API success/errors, timeout/API-error redaction, SDK `generate_content` request
  formation with a mocked HTTP transport, and a new synthetic pair.
- `npm run build` passed (TypeScript and production bundle).
- `npm run lint` passed with five pre-existing Fast Refresh warnings in untouched components.
- Python lint passed for the AI module, API, tests and scripts.
- Browser interaction QA could not run: Chromium was unavailable and its download timed out.
  The frontend is build-checked; a live browser smoke test remains to be done by the team.

| Sponsor case | Offline source/citation check | Live Gemini quality result |
|---|---|---|
| `response_1_weak` | Passed | NOT RUN: API key/model unavailable |
| `response_2_medium` | Passed | NOT RUN: API key/model unavailable |
| `response_3_strong` | Passed | NOT RUN: API key/model unavailable |
| `response_4_overpromise` | Passed | NOT RUN: API key/model unavailable |

Synthetic end-to-end logic/contract test passed with authored provider stubs.
Live unseen-pair generalization is **not yet verified**. The committed
`app/fixtures/evaluation-status/report.json` records that explicitly.

## Limitations / defendable claims

- Quote checks prove source presence and location, **not semantic entailment**.
  Extraction completeness, atomicity, mandatory interpretation, classification,
  scoring consistency and contradiction reasoning remain model judgments that
  need live evaluation and human review.
- Stable IDs are assigned in document order within a run; changed extraction
  granularity on another run can change later IDs. Temperature zero does not
  guarantee identical model output.
- Injection resistance includes isolated system instructions, documents serialized
  as data, strict schemas and no tools; this is not proof of immunity. The automated
  injection test checks the boundary, not live-model adversarial resistance.
- Each document is capped at 100,000 characters, extraction at 120 requirements.
  No chunking, PDF/PPT, OCR or vector search. Token-budget truncation fails explicitly.
- No automatic repair/retry or cache: invalid quotes/partial output require a retry
  from the user. This trades convenience for avoiding silently accepted findings.
- Progress reflects one whole request, not invented streamed model stages. Calls
  may take two configured timeouts; frontend timeout is 210 seconds by default.
- Suggested fixes are review actions, visibly separated from source evidence. Copy
  is available; automatic Apply/Preview is disabled for action-only output.
- Extra scope/fast timelines are presented as supported concerns needing validation,
  not automatically as contradictions or facts about feasibility.

Judge explanation: “The first call turns the client's RFP into an auditable matrix.
The second reviews the draft against that matrix and the full RFP. Code validates
citations and computes scoring/gates. You can inspect the exact source passages,
and a violated binding constraint blocks readiness even if the prose scores well.”

## Ready for teammates / remaining work

Frontend can already use the real `/api/review` route, original citation navigation,
four status counts, seven scores, contradiction jumps, suggested actions and gated
readiness. Use the synthetic JSON fixture to inspect the response shape immediately.

Backend/integration teammate still needs to:

1. Set a real Gemini key and accessible model; run all live evaluations and review
   false positives/negatives before demo. Do not report live scores until this passes.
2. Deploy the API, set the frontend API URL and allowed CORS origin. If n8n is desired,
   proxy the exact JSON request/response and preserve status codes; it is not required
   for the local core pipeline.
3. For public deployment, add the team's authentication/rate limit and request limits
   at the gateway. No new database is required for this slice.
4. Optionally add document conversion only after Markdown live behavior is verified.

The active SDK contract was checked against the installed `google-genai` package
and its [official structured-output documentation](https://ai.google.dev/gemini-api/docs/structured-output).
