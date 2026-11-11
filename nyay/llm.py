"""LLM layer on LangChain. Swap the model with one string, e.g.

    --lawyer groq:openai/gpt-oss-120b        (default, Groq free tier)
    --judge  groq:qwen/qwen3.8-27b           (a different model grades the answers)
    --lawyer openai:gpt-4.1-mini             (any provider LangChain's init_chat_model supports,
    --lawyer anthropic:claude-sonnet-5-5     once its integration package and API key are installed)

What this module adds on top of `init_chat_model`:
  * Pydantic structured output (`with_structured_output(Schema, method="json_schema")`)
  * a persistent SQLite LLM cache: same prompt + model => no tokens spent, identical result
  * a token-per-minute budget per model, because Groq's free tier allows ~8K tokens/min/model
  * retries with back-off on rate limits, plus a fallback model when the primary is exhausted
  * token usage accounting per model (for the cost table)
"""
from __future__ import annotations

import os
import re
import threading
import time
import warnings
from collections import deque
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.globals import set_llm_cache
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*allowed_objects.*")


def load_env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def enable_cache(path: Path = ROOT / ".cache" / "llm_cache.sqlite") -> None:
    from langchain_community.cache import SQLiteCache
    path.parent.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(path)))


class TokenBudget:
    """Sliding 60-second window so parallel calls stay under a provider's tokens-per-minute cap."""

    def __init__(self, tpm: int):
        self.tpm, self.events, self.lock = tpm, deque(), threading.Lock()

    def acquire(self, tokens: int) -> list:
        tokens = min(tokens, self.tpm)
        while True:
            with self.lock:
                now = time.time()
                while self.events and now - self.events[0][0] > 60:
                    self.events.popleft()
                used = sum(t for _, t in self.events)
                if used + tokens <= self.tpm:
                    ev = [now, tokens]
                    self.events.append(ev)
                    return ev
                wait = 60 - (now - self.events[0][0]) + 0.2
            time.sleep(max(0.5, wait))

    def refund(self, ev: list) -> None:
        """A cache hit spent no tokens: give the reservation back."""
        with self.lock:
            try:
                self.events.remove(ev)
            except ValueError:
                pass


def _unwrap(schema: type[BaseModel], raw):
    """Some models echo the JSON-schema envelope: {"description": .., "properties": {<the real answer>}}."""
    import json
    try:
        data = json.loads(str(getattr(raw, "content", "") or ""))
    except (ValueError, TypeError):
        return None
    for key in ("properties", "parameters", "data", "answer"):
        if isinstance(data, dict) and isinstance(data.get(key), dict):
            try:
                return schema.model_validate(data[key])
            except Exception:
                continue
    return None


USAGE: dict[str, dict] = {}
_usage_lock = threading.Lock()
_budgets: dict[str, TokenBudget] = {}


class LLM:
    """One role (picker / viewer) = one model string, its own token budget and an optional fallback."""

    def __init__(self, spec: str, tpm: int = 7800, max_tokens: int = 3000, fallback: str | None = None,
                 temperature: float = 0.2, otpm: int | None = None, expected_out: int = 400):
        """otpm: some Groq models also cap OUTPUT tokens per minute (qwen3.8-27b: 1,000)."""
        self.spec, self.max_tokens, self.fallback_spec = spec, max_tokens, fallback
        self.expected_out = expected_out
        self.model = self._make(spec, temperature)
        self.fallback = self._make(fallback, temperature) if fallback else None
        for s in filter(None, (spec, fallback)):
            _budgets.setdefault(s, TokenBudget(tpm))
            if otpm:
                _budgets.setdefault(s + "#out", TokenBudget(otpm))

    def _make(self, spec: str, temperature: float):
        provider, _, name = spec.partition(":")
        kwargs = {"temperature": temperature, "max_retries": 6, "max_tokens": self.max_tokens}
        if provider == "groq" and "gpt-oss" in name:
            kwargs["reasoning_effort"] = "low"      # reasoning tokens count against the free-tier budget
        return init_chat_model(name, model_provider=provider, **kwargs)

    def structured(self, schema: type[BaseModel], system: str, user: str) -> tuple[BaseModel, str]:
        """Returns (parsed Pydantic object, model spec that produced it)."""
        msgs = [SystemMessage(system), HumanMessage(user)]
        est = (len(system) + len(user)) // 4 + self.max_tokens     # Groq counts max_tokens against TPM up front
        last = None
        for spec, model in ((self.spec, self.model), (self.fallback_spec, self.fallback)):
            if model is None:
                continue
            runnable = model.with_structured_output(schema, method="json_schema", include_raw=True)
            for attempt in range(4):
                ev = _budgets[spec].acquire(est)
                ev_out = _budgets[spec + "#out"].acquire(self.expected_out) if spec + "#out" in _budgets else None
                t0 = time.time()
                try:
                    out = runnable.invoke(msgs)
                except Exception as e:
                    last = e
                    msg = str(e)
                    if "rate_limit" in msg.lower() and "per day" in msg.lower():
                        break                           # daily quota gone: go to the fallback model
                    if "parse" in msg.lower() or "validation" in msg.lower():
                        # the bad reply is now in the LLM cache; change the prompt so the retry is a fresh call
                        msgs = msgs[:2] + [HumanMessage(f"Your last answer failed validation: {msg[:300]}. "
                                                        "Answer again with every field of the schema.")]
                        continue
                    wait = re.search(r"try again in ([\d.]+)s", msg)          # Groq tells us how long to wait
                    time.sleep(float(wait.group(1)) + 1 if wait else 5 * (attempt + 1))
                    continue
                cache_hit = time.time() - t0 < 0.3
                if cache_hit:
                    _budgets[spec].refund(ev)
                    if ev_out:
                        _budgets[spec + "#out"].refund(ev_out)
                self._count(spec, out["raw"], cache_hit)
                if out.get("parsed") is not None:
                    return out["parsed"], spec
                rescued = _unwrap(schema, out.get("raw"))
                if rescued is not None:
                    return rescued, spec
                last = out.get("parsing_error")         # Pydantic rejected it: ask again
                msgs = msgs[:2] + [HumanMessage(f"Your last answer failed validation: {str(last)[:400]}. "
                                                "Answer again, following the schema exactly.")]
        raise RuntimeError(f"{self.spec} failed: {last}")

    def text(self, system: str, messages: list[tuple[str, str]]) -> str:
        """Free-text chat turn (used by practice mode). messages = [("user"|"assistant", text), ...]"""
        from langchain_core.messages import AIMessage
        msgs = [SystemMessage(system)] + [HumanMessage(t) if r == "user" else AIMessage(t) for r, t in messages]
        est = (len(system) + sum(len(t) for _, t in messages)) // 4 + self.max_tokens
        last = None
        for spec, model in ((self.spec, self.model), (self.fallback_spec, self.fallback)):
            if model is None:
                continue
            for attempt in range(4):
                _budgets[spec].acquire(est)
                try:
                    raw = model.invoke(msgs)
                except Exception as e:
                    last = e
                    if "per day" in str(e).lower():
                        break
                    time.sleep(5 * (attempt + 1))
                    continue
                self._count(spec, raw, False)
                return str(raw.content).strip()
        raise RuntimeError(f"{self.spec} failed: {last}")

    @staticmethod
    def _count(spec: str, raw, cache_hit: bool) -> None:
        u = getattr(raw, "usage_metadata", None) or {}
        with _usage_lock:
            d = USAGE.setdefault(spec, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0})
            if cache_hit:
                d["cache_hits"] += 1
                return
            d["calls"] += 1
            d["input_tokens"] += u.get("input_tokens", 0)
            d["output_tokens"] += u.get("output_tokens", 0)
