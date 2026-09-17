"""Routes: blocking /score, streaming /score/stream (event order, error event, keepalive)."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.aggregate import normalize_weights
from app.main import app, sse
from app.schema import (
    DocOutline,
    ErrorEvent,
    RequirementsEvent,
    ScoringMeta,
    ScoringResult,
    SectionsEvent,
    Signals,
)


def _result(overall: float | None = 1.7, weights=None, partial: bool = False) -> ScoringResult:
    return ScoringResult(
        overall=overall,
        weights=normalize_weights(weights),
        scores=[],
        coverage=[],
        constraintViolations=[],
        findings=[],
        requirements=[],
        constraints=[],
        suggestedWeights=[],
        signals=Signals(),
        sections={
            "rfp": DocOutline(count=0, sections=[]),
            "proposal": DocOutline(count=0, sections=[]),
        },
        partial=partial,
        error="boom" if partial else None,
        meta=ScoringMeta(model="m", temperature=0, promptVersion="t", durationMs=1),
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        if lines[0].startswith(":"):
            out.append(("ping", {}))
            continue
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        out.append((event, data))
    return out


def test_health_and_validation():
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}
    assert client.post("/score", json={"rfp": "r", "proposal": "  "}).status_code == 400
    assert client.post("/score/stream", json={"rfp": "r", "proposal": ""}).status_code == 400
    assert client.post("/score", json={"proposal": "p"}).status_code != 422  # rfp is optional


def test_score_blocking_returns_result_partial_and_error(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(app)

    async def fake(rfp, proposal, weights=None):
        return _result(weights=weights)

    monkeypatch.setattr(main, "score_proposal", fake)
    r = client.post("/score", json={"rfp": "r", "proposal": "p", "weights": {"completeness": 2}})
    assert r.status_code == 200 and r.json()["overall"] == 1.7
    assert r.json()["weights"]["completeness"] == 2.0 and r.json()["partial"] is False

    async def partial(rfp, proposal, weights=None):
        return _result(overall=None, partial=True)

    monkeypatch.setattr(main, "score_proposal", partial)
    r = client.post("/score", json={"rfp": "r", "proposal": "p"})
    assert r.status_code == 200 and r.json()["partial"] is True and r.json()["overall"] is None

    async def boom(rfp, proposal, weights=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(main, "score_proposal", boom)
    r = client.post("/score", json={"rfp": "r", "proposal": "p"})
    assert r.status_code == 502 and "ollama down" in r.json()["detail"]


def test_stream_emits_events_in_order(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(rfp, proposal, weights=None, provider=None):
        yield (
            "sections",
            SectionsEvent(
                rfp=DocOutline(count=1, sections=[]), proposal=DocOutline(count=2, sections=[])
            ),
        )
        yield (
            "requirements",
            RequirementsEvent(
                requirements=[], constraints=[], suggestedWeights=[], extractCached=True
            ),
        )
        yield "done", _result(weights=weights)

    monkeypatch.setattr(main, "run", fake_run)
    client = TestClient(app)
    with client.stream(
        "POST", "/score/stream", json={"rfp": "r", "proposal": "p", "weights": {"completeness": 2}}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-accel-buffering"] == "no"
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    assert [e for e, _ in events] == ["sections", "requirements", "done"]
    assert events[0][1]["proposal"]["count"] == 2
    assert events[1][1]["extractCached"] is True
    assert events[2][1]["overall"] == 1.7 and events[2][1]["weights"]["completeness"] == 2.0


def test_stream_turns_exception_into_error_event(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(rfp, proposal, weights=None, provider=None):
        yield (
            "sections",
            SectionsEvent(
                rfp=DocOutline(count=0, sections=[]), proposal=DocOutline(count=0, sections=[])
            ),
        )
        raise RuntimeError("ollama down")

    monkeypatch.setattr(main, "run", fake_run)
    client = TestClient(app)
    with client.stream("POST", "/score/stream", json={"rfp": "r", "proposal": "p"}) as r:
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    assert [e for e, _ in events] == ["sections", "error"]
    assert events[1][1] == {"stage": "sections", "error": "RuntimeError: ollama down"}
    ErrorEvent.model_validate(events[1][1])


def test_sse_pings_while_waiting():
    async def slow():
        yield (
            "sections",
            SectionsEvent(
                rfp=DocOutline(count=0, sections=[]), proposal=DocOutline(count=0, sections=[])
            ),
        )
        await asyncio.sleep(0.05)
        yield "done", _result()

    async def collect():
        return [chunk async for chunk in sse(slow(), ping=0.01)]

    chunks = asyncio.run(collect())
    assert chunks[0].startswith("event: sections\n")
    assert ": ping\n\n" in chunks[1:-1]
    assert chunks[-1].startswith("event: done\ndata: ")
