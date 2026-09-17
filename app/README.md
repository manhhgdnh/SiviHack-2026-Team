# Proposal Scorer — backend

FastAPI backend for the FPT "Proposal Scorer" track. It implements `../BACKEND.md` (the
v0 setup plan) on a **uv** project layout: `pyproject.toml` + `uv.lock` instead of
`requirements.txt`, package at `src/app/`, same module path (`uvicorn app.main:app`).

Pipeline: `POST /score {rfp, proposal, weights?}` → LLM call 1 extracts RFP requirements
(cached by hash of the RFP) → LLM call 2 scores 7 criteria + coverage + risks → every quote
is checked to be a verbatim substring of its source → weighted overall + prioritised
findings → `ScoringResult`.

## Run with Docker (the demo path)

```bash
cp .env.example .env        # ollama test mode by default
./run.sh up                 # build, start ollama + backend + nginx, pull qwen2.5:7b (~4.5 GB)
curl localhost/api/health   # {"ok":true}     docs: http://localhost/api/docs
./run.sh score              # weak sample through nginx
./run.sh regression         # all 4 samples; asserts weak < medium < strong, overpromise caught
```

Only nginx has a host port: `/api/*` → backend (prefix stripped), `/` → frontend service.
The `frontend` service is a placeholder; the real app is `../frontend`.

## Run locally (hot reload)

```bash
uv sync
docker compose up -d ollama && docker compose exec ollama ollama pull qwen2.5:7b
OLLAMA_URL=http://localhost:11434 uv run uvicorn app.main:app --reload   # :8000/docs
uv run pytest                 # offline acceptance tests (fake provider)
uv run ruff check . && uv run basedpyright
uv run --env-file .env python tests/regression.py    # needs a reachable LLM
```

## Switch to the provided LLM

Edit `.env`: `LLM_PROVIDER=remote`, `REMOTE_BASE_URL`, `REMOTE_API_KEY`, `REMOTE_MODEL`
(any OpenAI-compatible chat endpoint), then `docker compose up -d --build backend`.

## Layout

| BACKEND.md            | here                              |
|-----------------------|-----------------------------------|
| `backend/app/*.py`    | `src/app/*.py`                    |
| `requirements.txt`    | `pyproject.toml` + `uv.lock`      |
| `backend/data/*.md`   | `../sample_data/*.md` (mounted at `/sample_data` in the container) |
| `backend/data/cache/` | `data/cache/` (git-ignored)       |
| `frontend/schema.d.ts`| `schema.d.ts` (or generate from `/api/openapi.json`) |
| `backend/tests/regression.py` | `tests/regression.py`     |
