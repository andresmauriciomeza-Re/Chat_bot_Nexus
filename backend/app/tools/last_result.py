"""Ultimo resultado por usuario/chat (en RAM) con vencimiento de 30 minutos."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

LAST_RESULT_TTL = 30 * 60


@dataclass(slots=True)
class LastResult:
    kind: str                                  # recs | price | compare | similar | full
    games: list = field(default_factory=list)
    trm: float | None = None
    full_text: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


class LastResults:
    def __init__(self, ttl: float = LAST_RESULT_TTL, clock=time.time):
        self.ttl, self.clock = ttl, clock
        self._d: dict[tuple[int, int], LastResult] = {}
        self._full: dict[tuple[int, int], tuple[float, str]] = {}

    def save(self, user: int, chat: int, kind: str, games: list | None = None, trm: float | None = None,
             full_text: str | None = None, **extra) -> LastResult:
        r = LastResult(kind, list(games or []), trm, full_text, extra, self.clock())
        self._d[(user, chat)] = r
        return r

    def get(self, user: int, chat: int) -> LastResult | None:
        r = self._d.get((user, chat))
        if r is None:
            return None
        if self.clock() - r.ts > self.ttl:
            del self._d[(user, chat)]
            return None
        return r

    def save_full(self, user: int, chat: int, text: str) -> None:
        self._full[(user, chat)] = (self.clock(), text)

    def get_full(self, user: int, chat: int) -> str | None:
        v = self._full.get((user, chat))
        if v is None or self.clock() - v[0] > self.ttl:
            self._full.pop((user, chat), None)
            return None
        return v[1]

    def clear_user(self, user: int) -> None:
        for k in [k for k in self._full if k[0] == user]:
            del self._full[k]
        for k in [k for k in self._d if k[0] == user]:
            del self._d[k]
