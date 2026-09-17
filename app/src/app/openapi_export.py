"""Write the OpenAPI document the frontend generates its client from.

    uv run python -m app.openapi_export          # writes app/openapi.json
    uv run python -m app.openapi_export --check  # exit 1 when the file is stale

tests/test_openapi.py makes `uv run pytest` fail on the same drift, so the committed file,
the running app and the generated frontend client cannot disagree unnoticed.
"""

import json
import sys
from pathlib import Path

from app.main import app

PATH = Path(__file__).resolve().parents[2] / "openapi.json"  # app/openapi.json


def render() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    fresh = render()
    if "--check" in argv:
        stale = not PATH.exists() or PATH.read_text() != fresh
        print(
            "app/openapi.json is stale: run `uv run python -m app.openapi_export`"
            if stale
            else "app/openapi.json is up to date"
        )
        return int(stale)
    PATH.write_text(fresh)
    print(f"wrote {PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
