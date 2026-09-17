"""Recorded Gemini answers, keyed by the prompt text.

One file per distinct prompt: tests/fixtures/replay/<sha16>.json holding
{"kind", "model", "prompt_head", "truncated", "usage", "text"}. The prompt embeds the
documents, the rubric, the prompt version and the group id, so any edit to prompts.py or to a
sample changes the key; a miss raises ReplayMiss and never touches the network. Recording
wraps a real provider: hits are served from disk, misses call through and are written, so
re-recording after a prompt change only pays for the prompts that changed.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from app import config
from app.llm import Completion, JsonSchema, LlmProvider

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "replay"
_GROUP = re.compile(r"Group id: (\w+)")


def key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def classify(prompt: str) -> str:
    """Call kind from the prompt's opening words: extract / coverage / group:<id> / score."""
    if prompt.startswith("You extract"):
        return "extract"
    if prompt.startswith("You check"):
        return "coverage"
    if prompt.startswith("You score"):
        m = _GROUP.search(prompt)
        return f"group:{m.group(1)}" if m else "group:?"
    return "score"


class ReplayMiss(RuntimeError):
    """No recording for this prompt: an unseen document, or prompts.py changed."""


class ReplayProvider(LlmProvider):
    name = "replay"

    def __init__(
        self,
        directory: Path | None = None,
        fail: set[str] | None = None,
        delay_ms: int | None = None,
        model: str | None = None,
    ) -> None:
        self.dir = directory or (Path(config.REPLAY_DIR) if config.REPLAY_DIR else DEFAULT_DIR)
        # kinds that answer invalid JSON, to rehearse the degraded paths for free
        self.fail = set(fail) if fail is not None else set(config.REPLAY_FAIL)
        self.delay_ms = config.REPLAY_DELAY_MS if delay_ms is None else delay_ms
        # The model the fixtures were recorded with: cache keys and meta.model then match a
        # live run, so a replay with USE_CACHE=true warms the demo cache for free.
        self.model = model or config.GEMINI_MODEL

    def path(self, prompt: str) -> Path:
        return self.dir / f"{key(prompt)}.json"

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        kind = classify(prompt)
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        if kind in self.fail:
            return Completion("not json (LLM_REPLAY_FAIL)", False)
        f = self.path(prompt)
        if not f.exists():
            raise ReplayMiss(
                f"no recording for the {kind} prompt ({key(prompt)}) in {self.dir}: "
                "unseen document, or prompts changed — run tests/record_fixtures.py"
            )
        rec = json.loads(f.read_text())
        return Completion(rec["text"], bool(rec.get("truncated", False)))


class RecordingProvider(ReplayProvider):
    """Serve a hit from disk; on a miss call `inner` (Gemini), write the recording, return it."""

    def __init__(self, inner: LlmProvider, directory: Path | None = None) -> None:
        super().__init__(directory, fail=set(), delay_ms=0, model=inner.model)
        self.inner = inner
        self.name = inner.name  # split_mode, cache keys and usage rows follow the real provider
        self.recorded: list[str] = []

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        try:
            return await super().complete(prompt, schema, temperature, strict, reasoning)
        except ReplayMiss:
            pass
        c = await self.inner.complete(prompt, schema, temperature, strict, reasoning)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path(prompt).write_text(
            json.dumps(
                {
                    "kind": classify(prompt),
                    "model": self.inner.model,
                    "prompt_head": prompt[:80],
                    "truncated": c.truncated,
                    "usage": asdict(c.usage) if c.usage else None,
                    "text": c.text,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        self.recorded.append(classify(prompt))
        return c
