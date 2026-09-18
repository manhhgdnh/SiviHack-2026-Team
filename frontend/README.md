# Proposal Scorer — frontend

React 19 + Vite 8 + TypeScript + Tailwind v4, the review surface for the FastAPI backend in
`../app`. The design system is in `DESIGN.md`; the product brief in `PRODUCT.md`.

## Modes

| `VITE_API_URL` | What answers |
|---|---|
| unset (default) | the four recorded results in `src/api/fixtures/results/`, replayed as the backend's six frames; any other document is refused with a clear message |
| `/api` with `npm run dev` | the backend on `localhost:8000` through the Vite proxy (the backend can be live, or `LLM_PROVIDER=replay`) |
| `/api` in the compose stack | nginx → backend; the image bakes this in (`Dockerfile`) |

## Contract

`src/api/generated/` is generated from `../app/openapi.json` (`npm run api:gen`; `npm run
api:check` fails when it is stale). `src/api/schema.ts` is the UI's own vocabulary;
`src/api/adapt.ts` is the one place the two meet. `src/api/stream.ts` reads
`POST /score/stream` as typed frames validated with the generated zod schemas, so a backend
that drifted surfaces as a "contract" error naming the field, never as a crash.

## Export

`src/lib/export.ts` renders the review as one report model with two renderers: Markdown, and Word through the `docx` library. The band's "Export" menu offers both.

## Checks

`npm run build` (runs `tsc -b`) and `npm run lint`. Behaviour is verified by hand with
`../docs/verification.md`. There is no test runner by decision.
