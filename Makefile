# One command for every free check, and the few paid or stateful steps by name.
# No CI exists, and two toolchains do: `make check` before every push.
.PHONY: check test lint build gen record requirements warm spend demo

check: test lint build

test:
	cd app && uv run pytest -q

lint:
	cd app && uv run ruff check . && uv run ruff format --check . && uv run basedpyright
	cd frontend && npm run -s lint

build:            # tsc -b is the frontend type check
	cd frontend && npm run -s build

gen:              # backend contract → app/openapi.json → frontend/src/api/generated
	cd app && uv run python -m app.openapi_export
	cd frontend && npm run -s api:gen

record:           # costs money only for prompts without a recording
	cd app && uv run --env-file .env python tests/record_fixtures.py

requirements:
	cd app && uv export --no-dev --no-hashes --no-emit-project --no-header --format requirements-txt -o ../requirements.txt

warm:             # fill app/data/cache from the recordings, $0
	cd app && LLM_PROVIDER=replay USE_CACHE=true uv run --env-file .env python tests/regression.py

spend:
	cd app && uv run --env-file .env python -m app.usage

demo:
	cd app && docker compose up -d --build && curl -fsS localhost/api/health && echo && echo "open http://localhost"
