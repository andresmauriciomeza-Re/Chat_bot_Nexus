"""Guardia de riesgo: durante 30 min no hay tarjetas, animaciones, XP, voz, paneles ni mascota."""
from __future__ import annotations

import time

GUARD_SECONDS = 30 * 60


class RiskGuard:
    def __init__(self, seconds: float = GUARD_SECONDS, clock=time.time):
        self.seconds, self.clock = seconds, clock
        self._until: dict[str, float] = {}

    def mark(self, user: str | int) -> None:
        self._until[str(user)] = self.clock() + self.seconds

    def active(self, user: str | int | None) -> bool:
        if user is None:
            return False
        u = str(user)
        t = self._until.get(u)
        if t is None:
            return False
        if self.clock() >= t:
            del self._until[u]
            return False
        return True

    def release(self, user: str | int) -> None:
        self._until.pop(str(user), None)

    def forget(self, user: str | int) -> None:
        self.release(user)
