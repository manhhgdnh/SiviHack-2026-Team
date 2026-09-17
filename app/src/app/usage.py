"""Per-call usage log: one CSV row per LLM call with token counts and cost, a warning once
the day's spend passes the ceiling, and a hard stop at LLM_BUDGET_USD. It gives the pitch its
number ("one review is about $0.10") and makes a runaway loop physically unable to spend.

    uv run --env-file .env python -m app.usage    # today / total / budget
"""

import csv
import logging
from datetime import date, datetime
from pathlib import Path

from app import config
from app.llm import TokenUsage

log = logging.getLogger(__name__)

FILE = Path("data/usage.csv")
# Gemini 3.8 Flash on the Gemini API, USD per million tokens, list price to 31.12.2026.
# Output includes thinking; the cached rate applies to the cached part of the prompt.
PRICE_INPUT, PRICE_OUTPUT, PRICE_CACHED = 0.75, 3.75, 0.075
DAILY_CEILING_USD = 20.0
HEADER = ["time", "call", "model", "prompt", "output", "thinking", "cached", "usd"]

_warned = False


def cost(t: TokenUsage) -> float:
    fresh = max(t.prompt - t.cached, 0)
    return (
        fresh * PRICE_INPUT + t.cached * PRICE_CACHED + (t.output + t.thinking) * PRICE_OUTPUT
    ) / 1e6


def today_usd() -> float:
    if not FILE.exists():
        return 0.0
    day = date.today().isoformat()
    with FILE.open(newline="") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f) if r["time"].startswith(day))


def total_usd() -> float:
    """All-time spend on this machine (the project budget spans midnight)."""
    if not FILE.exists():
        return 0.0
    with FILE.open(newline="") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f))


class BudgetExceeded(RuntimeError):
    """LLM_BUDGET_USD reached: refuse to make another real call."""


def check_budget() -> None:
    """Called before every real call; cache hits never get here. Blank = unlimited."""
    if config.BUDGET_USD is None:
        return
    spent = total_usd()
    if spent >= config.BUDGET_USD:
        raise BudgetExceeded(
            f"LLM budget reached: ${spent:.2f} of ${config.BUDGET_USD:.2f} spent (see {FILE}); "
            "raise LLM_BUDGET_USD in .env to continue"
        )


def record(call: str, model: str, t: TokenUsage) -> None:
    """Append one row; a provider that reports no tokens (Ollama) leaves no row."""
    global _warned
    if not (t.prompt or t.output or t.thinking):
        return
    new = not FILE.exists()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        stamp = datetime.now().isoformat(timespec="seconds")
        w.writerow([stamp, call, model, t.prompt, t.output, t.thinking, t.cached, f"{cost(t):.6f}"])
    spent = today_usd()
    if spent > DAILY_CEILING_USD and not _warned:
        _warned = True
        log.warning(
            "LLM spend today is $%.2f, past the $%.0f ceiling: look for a loop",
            spent,
            DAILY_CEILING_USD,
        )


if __name__ == "__main__":
    limit = "unlimited" if config.BUDGET_USD is None else f"${config.BUDGET_USD:.2f}"
    print(f"today ${today_usd():.3f}   total ${total_usd():.3f}   budget {limit}")
