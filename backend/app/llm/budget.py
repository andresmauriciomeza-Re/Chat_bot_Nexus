"""Presupuesto global de tokens de Groq + cupo diario por usuario + enfriamiento por rate limit."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .base import LLMError, LLMProvider, LLMRateLimitError, LLMResult

log = logging.getLogger(__name__)
BOGOTA = timezone(timedelta(hours=-5))


class LLMBudgetError(LLMError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason     # "global" | "user" | "cooldown"


class TokenBudget:
    def __init__(self, enabled: bool = True, daily_tokens: int = 160_000, per_user_tokens: int = 20_000,
                 path: Path | None = None, cooldown_s: float = 30.0, clock=time.time):
        self.enabled, self.daily, self.per_user = enabled, daily_tokens, per_user_tokens
        self.path, self.cooldown_s, self.clock = path, cooldown_s, clock
        self._cool_until = 0.0
        self.day, self.total, self.users = self._today(), 0, {}
        self._load()

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), BOGOTA).strftime("%Y-%m-%d")

    def _roll(self) -> None:
        if self._today() != self.day:
            self.day, self.total, self.users = self._today(), 0, {}
            self._save()

    def _load(self) -> None:
        try:
            if self.path and self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if d.get("day") == self.day:
                    self.total, self.users = int(d.get("total", 0)), dict(d.get("users", {}))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"day": self.day, "total": self.total, "users": self.users}), encoding="utf-8")
        except OSError:
            pass

    def check(self, user: str | None, estimate: int = 0) -> str | None:
        if not self.enabled:
            return None
        self._roll()
        if self.clock() < self._cool_until:
            return "cooldown"
        if self.total + estimate > self.daily:
            return "global"
        if user is not None and self.users.get(user, 0) + estimate > self.per_user:
            return "user"
        return None

    def record(self, user: str | None, tokens: int) -> None:
        self._roll()
        self.total += tokens
        if user is not None:
            self.users[user] = self.users.get(user, 0) + tokens
        self._save()

    def rate_limited(self) -> None:
        self._cool_until = self.clock() + self.cooldown_s

    def forget_user(self, user: str) -> None:
        if self.users.pop(user, None) is not None:
            self._save()

    def remaining(self) -> int:
        self._roll()
        return max(0, self.daily - self.total)


class BudgetedLLM:
    """Envuelve un LLMProvider aplicando el presupuesto."""

    def __init__(self, inner: LLMProvider, budget: TokenBudget):
        self.inner, self.budget = inner, budget

    async def complete(self, messages: list[dict], max_tokens: int = 350, user: str | None = None) -> LLMResult:
        est = sum(len(m["content"]) for m in messages) // 3 + max_tokens
        reason = self.budget.check(user, est)
        if reason:
            raise LLMBudgetError(reason)
        try:
            res = await self.inner.complete(messages, max_tokens)
        except LLMRateLimitError:
            self.budget.rate_limited()
            raise
        self.budget.record(user, res.tokens or est)
        return res

    VOICE_TOKEN_COST = 300      # estimacion por nota de voz para el cupo

    async def transcribe(self, audio: bytes, user: str | None = None, **kw) -> str:
        reason = self.budget.check(user, self.VOICE_TOKEN_COST)
        if reason:
            raise LLMBudgetError(reason)
        try:
            text = await self.inner.transcribe(audio, **kw)
        except LLMRateLimitError:
            self.budget.rate_limited()
            raise
        self.budget.record(user, self.VOICE_TOKEN_COST)
        return text
