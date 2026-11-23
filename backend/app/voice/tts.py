"""Texto a voz con edge-tts. OGG/OPUS si hay ffmpeg; MP3 como respaldo (no se asume ffmpeg instalado)."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
from typing import Awaitable, Callable

log = logging.getLogger(__name__)
VOICES = {"salome": "es-CO-SalomeNeural", "gonzalo": "es-CO-GonzaloNeural"}
SPEECH_LIMIT = 600
_TAGS = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")

Synth = Callable[[str, str], Awaitable[bytes]]


def clean_for_speech(text: str, limit: int = SPEECH_LIMIT) -> str:
    t = html.unescape(_TAGS.sub(" ", text or ""))
    t = _URL.sub("", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", ". ", t).replace("..", ".").strip()
    if len(t) > limit:
        cut = max(t.rfind(". ", 0, limit), t.rfind(" ", 0, limit))
        t = t[: cut if cut > limit // 2 else limit].rstrip(" ,;") + "."
    return t


async def edge_synth(text: str, voice: str) -> bytes:
    import edge_tts
    data = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk.get("type") == "audio":
            data += chunk["data"]
    return bytes(data)


class TTS:
    def __init__(self, synth: Synth = edge_synth, ffmpeg: str | None | bool = True, timeout: float = 25.0):
        self.synth, self.timeout = synth, timeout
        self.ffmpeg = shutil.which("ffmpeg") if ffmpeg is True else (ffmpeg or None)

    @property
    def format_name(self) -> str:
        return "OGG/OPUS" if self.ffmpeg else "MP3"

    async def _to_opus(self, mp3: bytes) -> bytes | None:
        if not self.ffmpeg:
            return None
        try:
            p = await asyncio.create_subprocess_exec(
                self.ffmpeg, "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(mp3), timeout=20)
            return out if p.returncode == 0 and out else None
        except (OSError, asyncio.TimeoutError, ValueError):
            log.warning("ffmpeg no pudo convertir; uso MP3")
            return None

    async def speak(self, text: str, voice_key: str = "salome") -> tuple[bytes, str] | None:
        """(audio, 'ogg'|'mp3') o None si no se pudo. Nunca lanza."""
        clean = clean_for_speech(text)
        if not clean:
            return None
        voice = VOICES.get(voice_key, VOICES["salome"])
        try:
            mp3 = await asyncio.wait_for(self.synth(clean, voice), timeout=self.timeout)
        except Exception as e:
            log.warning("TTS fallo (%s)", type(e).__name__)
            return None
        if not mp3:
            return None
        opus = await self._to_opus(mp3)
        return (opus, "ogg") if opus else (mp3, "mp3")
