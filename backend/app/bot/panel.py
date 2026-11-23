"""Panel principal: cuadricula inline con la mascota. Cada boton EDITA el mismo mensaje y trae '⬅️ Menu'."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..telegram_utils import TG_MESSAGE_LIMIT
from . import callbacks as cbm
from .mascot import Mascot
from .send import safe_edit, send_text

log = logging.getLogger(__name__)
FOOTER_LIMIT = 900
GRID = [
    [("🎮 Recomiéndame", "reco"), ("💰 Por presupuesto", "budget")],
    [("😊 Mi ánimo", "mood"), ("🆓 Gratis hoy", "free")],
    [("🏆 Mi perfil", "profile"), ("🎁 Cofre", "chest")],
    [("🧠 Trivia", "trivia"), ("💜 Mis gustos", "likes")],
    [("🤖 Conocer a NEXUS", "about"), ("🔊 Voz y ajustes", "settings")],
    [("❓ Ayuda", "help"), ("💡 Consejo de NEXUS", "tip")],
]


@dataclass(slots=True)
class View:
    text: str
    mascot: str = "welcome"
    rows: list[list[InlineKeyboardButton]] = field(default_factory=list)
    full: str | None = None
    no_menu: bool = False


@dataclass(slots=True)
class ViewCtx:
    user_id: int
    chat_id: int
    arg: str
    app: Any                     # bot_data (servicios)


ViewFn = Callable[[ViewCtx], Awaitable[View]]


def fit_footer(text: str, limit: int = FOOTER_LIMIT) -> tuple[str, bool]:
    """Recorta en limite de LINEA (nunca a mitad de una etiqueta HTML). (texto, fue_recortado)"""
    if len(text) <= limit:
        return text, False
    out, n = [], 0
    for line in text.split("\n"):
        if n + len(line) + 1 > limit - 2:
            break
        out.append(line)
        n += len(line) + 1
    if not out:                       # una sola linea gigante: cortar y quitar etiquetas
        import re
        return re.sub(r"<[^>]*>", "", text)[: limit - 2] + "…", True
    return "\n".join(out).rstrip() + "\n…", True


class Panel:
    def __init__(self, mascot: Mascot, enabled: bool = True):
        self.mascot, self.enabled = mascot, enabled
        self.views: dict[str, ViewFn] = {}

    def register(self, name: str, fn: ViewFn) -> None:
        self.views[name] = fn

    async def build(self, name: str, ctx: ViewCtx) -> View:
        fn = self.views.get(name)
        if fn is None:
            return View("Esa opción llega pronto 🚧", "sleepy")
        try:
            return await fn(ctx)
        except Exception:
            log.exception("vista %s fallo", name)
            return View("Uy, no pude armar eso ahorita. Intenta de nuevo 🙏", "sad")

    def menu_markup(self, owner: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=cbm.make("v", owner, view))
                                      for label, view in row] for row in GRID])

    def _finalize(self, view: View, ctx: ViewCtx) -> tuple[str, InlineKeyboardMarkup]:
        text, cut = fit_footer(view.text)
        rows = [list(r) for r in view.rows]
        if cut:
            full = view.full or view.text
            ctx.app["last"].save_full(ctx.user_id, ctx.chat_id, full)
            rows.append([InlineKeyboardButton("📄 Ver todo", callback_data=cbm.make("fa", ctx.user_id))])
        if not view.no_menu:
            rows.append([InlineKeyboardButton("⬅️ Menú", callback_data=cbm.make("v", ctx.user_id, "menu"))])
        return text, InlineKeyboardMarkup(rows)

    def view_markup(self, name: str, view: View, ctx: ViewCtx):
        if name == "menu":
            return fit_footer(view.text)[0], self.menu_markup(ctx.user_id)
        return self._finalize(view, ctx)

    async def send(self, bot, chat_id: int, user_id: int, name: str, arg: str, app: Any):
        ctx = ViewCtx(user_id, chat_id, arg, app)
        view = await self.build(name, ctx)
        text, markup = self.view_markup(name, view, ctx)
        if self.enabled:
            msg = await self.mascot.send(bot, chat_id, view.mascot, text, markup)
            if msg:
                return msg
        return await send_text(bot, text, chat_id=chat_id, reply_markup=markup)

    async def edit(self, message, user_id: int, name: str, arg: str, app: Any) -> bool:
        ctx = ViewCtx(user_id, message.chat_id, arg, app)
        view = await self.build(name, ctx)
        text, markup = self.view_markup(name, view, ctx)
        has_media = bool(message.photo or message.animation or message.video)
        if has_media:
            if self.enabled and await self.mascot.edit(message, view.mascot, text, markup):
                return True
            try:
                await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)
                return True
            except Exception as e:
                return "not modified" in str(e).lower()
        return await safe_edit(message, text, markup)
