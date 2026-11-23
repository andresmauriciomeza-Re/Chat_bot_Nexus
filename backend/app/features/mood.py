"""Animo del usuario: SOLO en RAM, con vencimiento de 2 h. Nunca se escribe a disco."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..games.filters import Filters

MOOD_TTL = 2 * 3600


@dataclass(frozen=True, slots=True)
class Mood:
    key: str
    label: str
    mascot: str
    phrase: str
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def filters(self) -> Filters:
        return Filters(genres=set(self.genres), tags=set(self.tags))


MOODS: dict[str, Mood] = {m.key: m for m in [
    Mood("feliz", "😄 Feliz", "happy", "¡Qué chimba! Aprovechemos esa buena energía con algo para compartir.", tags=("coop",)),
    Mood("triste", "😢 Triste", "sad", "Aquí estoy, parce. Algo bonito y tranquilo puede acompañarte.", tags=("relajado", "historia")),
    Mood("estresado", "😣 Estresado", "stressed", "Respira. Vamos con algo relajante para soltar la tensión.", tags=("relajado",)),
    Mood("enojado", "😠 Enojado", "angry", "Toca desahogarse un poquito: acción sin filtro.", genres=("accion",)),
    Mood("cansado", "😴 Cansado", "sleepy", "Sin esfuerzo: algo cortico y suave.", tags=("corto", "relajado")),
    Mood("emocionado", "🤩 Emocionado", "excited", "¡Eso! Vamos por algo con reto.", tags=("desafiante",)),
    Mood("relajado", "😌 Relajado", "relaxed", "Plan tranquilo: algo para disfrutar sin afán.", tags=("relajado",)),
]}


class MoodStore:
    def __init__(self, ttl: float = MOOD_TTL, clock=time.time):
        self.ttl, self.clock = ttl, clock
        self._d: dict[int, tuple[str, float]] = {}

    def set(self, user: int, key: str) -> Mood | None:
        if key not in MOODS:
            return None
        self._d[user] = (key, self.clock())
        return MOODS[key]

    def get(self, user: int) -> Mood | None:
        v = self._d.get(user)
        if not v:
            return None
        if self.clock() - v[1] > self.ttl:
            del self._d[user]
            return None
        return MOODS[v[0]]

    def clear(self, user: int) -> None:
        self._d.pop(user, None)
