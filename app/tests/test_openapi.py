"""The committed OpenAPI document is the wire contract the frontend generates from: it must
match the running app, and it must carry everything a generator needs."""

import json

from app.main import app
from app.openapi_export import PATH


def test_committed_openapi_matches_the_app():
    assert PATH.exists(), "run `uv run python -m app.openapi_export`"
    assert json.loads(PATH.read_text()) == app.openapi(), (
        "app/openapi.json is stale: run `uv run python -m app.openapi_export`"
    )


def test_contract_carries_everything_a_generator_needs():
    spec = app.openapi()
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert ops == {"meta_health", "score_score", "score_stream", "rfp_extract"}
    c = spec["components"]["schemas"]

    disc = c["StreamEvent"]["discriminator"]
    assert disc["propertyName"] == "event" and len(disc["mapping"]) == 7
    stream = spec["paths"]["/score/stream"]["post"]["responses"]
    assert list(stream["200"]["content"]) == ["text/event-stream"]
    assert stream["200"]["content"]["text/event-stream"]["schema"] == {
        "$ref": "#/components/schemas/StreamEvent"
    }
    assert stream["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorDetail"
    }
    for path in ("/score", "/rfp/extract"):
        for code in ("400", "502"):
            body = spec["paths"][path]["post"]["responses"][code]["content"]["application/json"]
            assert body["schema"] == {"$ref": "#/components/schemas/ErrorDetail"}

    result = c["ScoringResult"]
    assert result["properties"]["sections"] == {"$ref": "#/components/schemas/Outlines"}
    assert result["properties"]["weights"] == {"$ref": "#/components/schemas/Weights"}
    assert c["Weights"]["propertyNames"] == {"$ref": "#/components/schemas/CriterionId"}
    assert {"quote", "grounding"} <= set(c["Citation"]["required"])
    assert {"partial", "warnings", "error"} <= set(result["required"])
    assert not [k for k in c if k.endswith("-Input") or k.endswith("-Output")]
