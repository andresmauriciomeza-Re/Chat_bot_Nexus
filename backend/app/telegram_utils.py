from __future__ import annotations

import html

TG_MESSAGE_LIMIT = 4096
TG_CAPTION_LIMIT = 1024


def esc(s: object) -> str:
    """Escapa HTML dinamico."""
    return html.escape(str(s), quote=False)


def split_text(text: str, limit: int = TG_MESSAGE_LIMIT) -> list[str]:
    parts: list[str] = []
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
