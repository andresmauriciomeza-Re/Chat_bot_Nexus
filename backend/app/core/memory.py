from __future__ import annotations

from collections import defaultdict, deque

MAX_STORED = 40


class ConversationMemory:
    """Historial en RAM por conversacion."""

    def __init__(self, max_stored: int = MAX_STORED):
        self._data: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_stored))

    def add(self, key: str, role: str, content: str) -> None:
        self._data[key].append({"role": role, "content": content})

    def get(self, key: str, limit: int) -> list[dict]:
        items = list(self._data.get(key, ()))
        return items[-limit:] if limit > 0 else []

    def clear(self, key: str) -> None:
        self._data.pop(key, None)
