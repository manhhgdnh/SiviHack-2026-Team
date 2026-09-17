"""Routes: blocking /score, streaming /score/stream (frame shape, event order, error frame,
keepalive), /rfp/extract, and the declared error bodies."""

import asyncio
import json

import fastapi.routing
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app import main
from app.aggregate import normalize_weights
from app.main import app
from app.schema import (
    DocOutline,
    ErrorEvent,
    Outlines,
    RequirementsEvent,
    ScoringMeta,
    ScoringResult,
    Signals,
    StreamEvent,
)

FRAME = TypeAdapter(StreamEvent)


def _outlines(rfp: int = 0, proposal: int = 0) -> Outlines:
    return Outlines(
        rfp=DocOutline(count=rfp, sections=[]), proposal=DocOutline(count=proposal, sections=[])
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
        sections=_outlines(),
        partial=partial,
        error="boom" if partial else None,
        meta=ScoringMeta(model="m", temperature=0, promptVersion="t", durationMs=1),
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Frames as (event, data); a comment-only block is ("ping", {})."""
    out = []
    for block in text.strip().split("\n\n"):
        event, data = None, []
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        if event is None and not data:
            out.append(("ping", {}))
        else:
            out.append((event or "message", json.loads("\n".join(data))))
    return out


def _frames(text: str) -> list[tuple[str, dict]]:
    """Parse and validate every non-ping frame against schema.StreamEvent."""
    events = _parse_sse(text)
    for event, data in events:
        if event != "ping":
            FRAME.validate_python({"event": event, "data": data})
    return events


def test_health_and_validation():
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}
    r = client.post("/score", json={"rfp": "r", "proposal": "  "})
    assert r.status_code == 400 and r.json() == {"detail": "proposal is required (rfp is optional)"}
    r = client.post("/score/stream", json={"rfp": "r", "proposal": ""})
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/json")
    assert client.post("/score", json={"proposal": "p"}).status_code != 422  # rfp is optional
    assert client.post("/score", json={"proposal": "p", "weights": {"bogus": 1}}).status_code == 422
    assert client.post("/rfp/extract", json={"rfp": " "}).status_code == 400


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
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "score_proposal", boom)
    r = client.post("/score", json={"rfp": "r", "proposal": "p"})
    assert r.status_code == 502 and "gemini down" in r.json()["detail"]


def test_stream_emits_events_in_order(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(rfp, proposal, weights=None, provider=None):
        yield "sections", _outlines(1, 2)
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
    events = _frames(body)
    assert [e for e, _ in events] == ["sections", "requirements", "done"]
    assert events[0][1]["proposal"]["count"] == 2
    assert events[1][1]["extractCached"] is True
    assert events[2][1]["overall"] == 1.7 and events[2][1]["weights"]["completeness"] == 2.0


def test_stream_turns_exception_into_error_event(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(rfp, proposal, weights=None, provider=None):
        yield "sections", _outlines()
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "run", fake_run)
    client = TestClient(app)
    with client.stream("POST", "/score/stream", json={"rfp": "r", "proposal": "p"}) as r:
        body = "".join(r.iter_text())
    events = _frames(body)
    assert [e for e, _ in events] == ["sections", "error"]
    assert events[1][1] == {"stage": "sections", "error": "RuntimeError: gemini down"}
    ErrorEvent.model_validate(events[1][1])


def test_sse_pings_while_waiting(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fastapi.routing, "_PING_INTERVAL", 0.01)

    async def slow(rfp, proposal, weights=None, provider=None):
        yield "sections", _outlines()
        await asyncio.sleep(0.05)
        yield "done", _result()

    monkeypatch.setattr(main, "run", slow)
    client = TestClient(app)
    with client.stream("POST", "/score/stream", json={"rfp": "r", "proposal": "p"}) as r:
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    assert events[0][0] == "sections" and events[-1][0] == "done"
    assert ("ping", {}) in events[1:-1]


def test_rfp_extract_maps_success_and_failure(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(app)

    async def fake(rfp, provider=None):
        return RequirementsEvent(
            requirements=[], constraints=[], suggestedWeights=[], extractCached=True
        )

    monkeypatch.setattr(main, "extract_requirements", fake)
    r = client.post("/rfp/extract", json={"rfp": "# RFP\nneed x"})
    assert r.status_code == 200 and r.json()["extractCached"] is True

    async def boom(rfp, provider=None):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "extract_requirements", boom)
    r = client.post("/rfp/extract", json={"rfp": "# RFP"})
    assert r.status_code == 502 and "gemini down" in r.json()["detail"]
