"""Mascota: animacion (.mp4/.gif) > imagen (.png/.jpg) > welcome > texto. Sube cada archivo una vez (file_id)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from telegram import InputMediaAnimation, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import TelegramError

log = logging.getLogger(__name__)

NAMES = ["welcome", "thinking", "happy", "sad", "angry", "sleepy", "stressed", "excited", "relaxed",
         "gift", "trophy", "quiz"]
ANIM_EXT = (".mp4", ".gif")
IMG_EXT = (".png", ".jpg", ".jpeg")
MAX_BYTES = 10 * 1024 * 1024


def _valid(path: Path) -> bool:
    """Descarta archivos vacios, enormes o corruptos (firma de cabecera)."""
    try:
        if not path.is_file() or not (0 < path.stat().st_size <= MAX_BYTES):
            return False
        with path.open("rb") as f:
            head = f.read(16)
    except OSError:
        return False
    ext = path.suffix.lower()
    if ext == ".png":
        return head.startswith(b"\x89PNG")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8")
    if ext == ".gif":
        return head[:4] == b"GIF8"
    if ext == ".mp4":
        return head[4:8] == b"ftyp"
    return False


@dataclass(slots=True)
class Asset:
    name: str
    kind: str            # "animation" | "photo"
    path: Path

    @property
    def key(self) -> str:
        st = self.path.stat()
        return f"{self.path.name}:{st.st_size}:{int(st.st_mtime)}"


class Mascot:
    def __init__(self, directory: Path, enabled: bool = True, anim_enabled: bool = True,
                 store_path: Path | None = None):
        self.dir, self.enabled, self.anim_enabled, self.store_path = directory, enabled, anim_enabled, store_path
        self._ids: dict[str, str] = {}
        self._load()
        self.assets: dict[str, Asset] = {}
        self.scan()

    # ---- indice de archivos ----
    def scan(self) -> list[str]:
        self.assets.clear()
        if not self.enabled:
            return []
        for name in NAMES:
            cands: list[tuple[str, Path]] = []
            if self.anim_enabled:
                cands += [("animation", self.dir / f"{name}{e}") for e in ANIM_EXT]
            cands += [("photo", self.dir / f"{name}{e}") for e in IMG_EXT]
            for kind, p in cands:                      # prioridad: animacion > imagen
                if _valid(p):
                    self.assets[name] = Asset(name, kind, p)
                    break
        log.info("mascota: %s", ", ".join(f"{a.name}({a.kind})" for a in self.assets.values()) or "sin archivos (modo texto)")
        return list(self.assets)

    def resolve(self, name: str) -> Asset | None:
        return self.assets.get(name) or self.assets.get("welcome")

    # ---- file_id ----
    def _load(self) -> None:
        try:
            if self.store_path and self.store_path.exists():
                self._ids = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._ids = {}

    def _remember(self, asset: Asset, file_id: str) -> None:
        self._ids[asset.key] = file_id
        if self.store_path:
            try:
                self.store_path.parent.mkdir(parents=True, exist_ok=True)
                self.store_path.write_text(json.dumps(self._ids), encoding="utf-8")
            except OSError:
                pass

    def _media(self, asset: Asset):
        fid = self._ids.get(asset.key)
        if fid:
            return fid, True
        return asset.path.open("rb"), False

    @staticmethod
    def _file_id(msg, asset: Asset) -> str | None:
        if msg is None:
            return None
        if asset.kind == "animation" and getattr(msg, "animation", None):
            return msg.animation.file_id
        if getattr(msg, "photo", None):
            return msg.photo[-1].file_id
        return None

    # ---- envio ----
    async def send(self, bot, chat_id: int, name: str, caption: str, reply_markup=None):
        """Envia mascota con caption. None si no hay archivo o fallo (el llamador usa texto)."""
        asset = self.resolve(name)
        if not asset:
            return None
        media, cached = self._media(asset)
        try:
            kw = dict(chat_id=chat_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            if asset.kind == "animation":
                msg = await bot.send_animation(animation=media, **kw)
            else:
                msg = await bot.send_photo(photo=media, **kw)
        except TelegramError as e:
            log.warning("mascota %s no se pudo enviar (%s)", asset.name, type(e).__name__)
            if cached:                                  # file_id viejo: olvidarlo
                self._ids.pop(asset.key, None)
            return None
        finally:
            if not cached and hasattr(media, "close"):
                media.close()
        if not cached:
            fid = self._file_id(msg, asset)
            if fid:
                self._remember(asset, fid)
        return msg

    async def edit(self, message, name: str, caption: str, reply_markup=None) -> bool:
        """Cambia la mascota y el pie de un mensaje con media. False si no se pudo."""
        asset = self.resolve(name)
        if not asset:
            return False
        media, cached = self._media(asset)
        try:
            cls = InputMediaAnimation if asset.kind == "animation" else InputMediaPhoto
            m = cls(media=media, caption=caption, parse_mode=ParseMode.HTML)
            res = await message.edit_media(media=m, reply_markup=reply_markup)
            if not cached:
                fid = self._file_id(res if not isinstance(res, bool) else None, asset)
                if fid:
                    self._remember(asset, fid)
            return True
        except TelegramError as e:
            if "not modified" in str(e).lower():
                return True
            log.warning("mascota %s no se pudo editar (%s)", asset.name, type(e).__name__)
            return False
        finally:
            if not cached and hasattr(media, "close"):
                media.close()
