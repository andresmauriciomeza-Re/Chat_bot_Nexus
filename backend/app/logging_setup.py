"""Logging con enmascarado de secretos (consola y, opcional, archivo)."""
from __future__ import annotations

import logging
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{25,}\b"),      # token de Telegram
    re.compile(r"\bgsk_[A-Za-z0-9]{10,}\b"),            # clave de Groq
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._-]{10,}"),
]
_BOT_URL = re.compile(r"/bot[^/\s]+/")
_extra: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        _extra.add(value)


def mask(text: str) -> str:
    for s in _extra:
        text = text.replace(s, "***")
    for p in _PATTERNS:
        text = p.sub("***", text)
    return _BOT_URL.sub("/bot***/", text)


class MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask(record.getMessage())
            record.args = ()
            if record.exc_info:  # el traceback puede traer URLs con token
                record.exc_text = mask("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None
        except Exception:  # nunca romper por logging
            record.msg, record.args = "<log no representable>", ()
        return True


def setup_logging(level: str = "INFO", to_file: bool = False, log_dir: str | Path = "logs",
                  secrets: list[str] | None = None) -> None:
    for s in secrets or []:
        register_secret(s)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        p = Path(log_dir)
        p.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(p / "nexus.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(MaskFilter())
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "telegram.ext", "hpack", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
