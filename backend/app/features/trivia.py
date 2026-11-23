"""Trivia de videojuegos (backend/config/trivia.json)."""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

from ..config import BACKEND_DIR

log = logging.getLogger(__name__)
TRIVIA_PATH = BACKEND_DIR / "config" / "trivia.json"


@dataclass(slots=True)
class Question:
    q: str
    options: list[str]
    answer: int
    explain: str = ""
    revisar: bool = True


def load_questions(path: Path = TRIVIA_PATH) -> list[Question]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))["questions"]
    except (OSError, ValueError, KeyError):
        log.warning("trivia.json no disponible: trivia desactivada")
        return []
    out = []
    for r in raw:
        try:
            q = Question(r["q"], list(r["options"]), int(r["answer"]), r.get("explain", ""), bool(r.get("revisar", True)))
            if len(q.options) >= 2 and 0 <= q.answer < len(q.options):
                out.append(q)
        except (KeyError, TypeError, ValueError):
            continue
    return out


class Trivia:
    def __init__(self, questions: list[Question] | None = None, rng: random.Random | None = None):
        self.questions = load_questions() if questions is None else questions
        self.rng = rng or random.Random()
        self._last: dict[int, int] = {}

    def __bool__(self) -> bool:
        return bool(self.questions)

    def pick(self, user: int) -> tuple[int, Question]:
        ids = [i for i in range(len(self.questions)) if i != self._last.get(user)] or [0]
        i = self.rng.choice(ids)
        self._last[user] = i
        return i, self.questions[i]

    def check(self, qid: int, opt: int) -> tuple[bool, Question] | None:
        if not (0 <= qid < len(self.questions)):
            return None
        q = self.questions[qid]
        return opt == q.answer, q

    def forget(self, user: int) -> None:
        self._last.pop(user, None)
