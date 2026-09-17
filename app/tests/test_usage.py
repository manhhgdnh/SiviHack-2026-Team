"""Usage log: one row per call, cost at list price, the daily ceiling warning."""

import csv
import logging
from pathlib import Path

import pytest

from app import usage
from app.llm import TokenUsage


def _to_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    f = tmp_path / "usage.csv"
    monkeypatch.setattr(usage, "FILE", f)
    monkeypatch.setattr(usage, "_warned", False)
    return f


def test_cost_at_list_price():
    assert usage.cost(TokenUsage(prompt=1_000_000)) == pytest.approx(0.75)
    assert usage.cost(TokenUsage(output=1_000_000)) == pytest.approx(3.75)
    assert usage.cost(TokenUsage(thinking=1_000_000)) == pytest.approx(3.75)  # billed as output
    assert usage.cost(TokenUsage(prompt=1_000_000, cached=1_000_000)) == pytest.approx(0.075)


def test_record_writes_one_row_per_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    f = _to_tmp(monkeypatch, tmp_path)
    usage.record("extract", "gemini-x", TokenUsage(prompt=9000, output=1500, thinking=800))
    usage.record("score", "gemini-x", TokenUsage())  # Ollama-style: nothing reported, no row
    usage.record("score", "gemini-x", TokenUsage(prompt=9000, output=2000))
    rows = list(csv.DictReader(f.open()))
    assert [r["call"] for r in rows] == ["extract", "score"]
    assert rows[0]["thinking"] == "800" and float(rows[0]["usd"]) == pytest.approx(0.015375)
    assert usage.today_usd() == pytest.approx(0.015375 + 0.01425)


def test_ceiling_warns_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog):
    _to_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(usage, "DAILY_CEILING_USD", 0.01)
    with caplog.at_level(logging.WARNING, logger="app.usage"):
        usage.record("score", "gemini-x", TokenUsage(output=5000))  # $0.01875
        usage.record("score", "gemini-x", TokenUsage(output=5000))
    assert sum("ceiling" in r.message for r in caplog.records) == 1
