"""Handlers de Telegram. La seguridad emocional se evalua SIEMPRE primero."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction, ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..core.safety import GUARD_SOFT
from ..games.budget import Amount
from ..games.filters import Filters
from ..games.render import render_sheet
from ..games.service import build_reason
from ..telegram_utils import esc
from . import callbacks as cbm
from .cards import send_reply, send_card
from .keyboard import label_to_view, main_keyboard
from .panel import Panel
from .send import _retry, safe_edit, send_text
from .views import HELP

log = logging.getLogger(__name__)
CONFETTI_EFFECT_ID = "5046509860389126442"
PRIVATE_ONLY_MSG = "Eso lo hacemos por chat privado 😉 Escríbeme directo."
RC_TAGS = {"relajado", "coop"}
ExtraCb = Callable[["BotHandlers", Update, cbm.CB], Awaitable[None]]


class BotHandlers:
    def __init__(self, A: dict, panel: Panel):
        self.A, self.panel = A, panel
        self.s = A["settings"]
        self.safety, self.pipe, self.svc, self.last = A["safety"], A["pipe"], A["svc"], A["last"]
        self.extra_cb: dict[str, ExtraCb] = {}
        self.erasers: list[Callable[[int], None]] = []
        self.announce = self._noop_announce

    @staticmethod
    async def _noop_announce(bot, chat, ev) -> None:
        return None

    async def after_view(self, update: Update, name: str) -> None:
        st = self.A.get("store")
        if st and name == "free":
            await self.announce(update.get_bot(), update.effective_chat.id, st.on_free(update.effective_user.id))

    # ---------- utilidades ----------
    @staticmethod
    def is_private(update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)

    def panel_ok(self, update: Update) -> bool:
        return self.s.main_panel_enabled and self.is_private(update)

    async def blocked_by_risk(self, update: Update) -> bool:
        u = update.effective_user
        if u and self.safety.active(u.id):
            if update.callback_query:
                await update.callback_query.answer()
                await send_text(update.callback_query.message.get_bot(), GUARD_SOFT, chat_id=update.effective_chat.id)
            else:
                await send_text(update.effective_message, GUARD_SOFT)
            return True
        return False

    async def open_view(self, update: Update, name: str, arg: str = "") -> None:
        chat, user = update.effective_chat, update.effective_user
        if not self.panel_ok(update):
            await send_text(update.effective_message, HELP if self.is_private(update) else PRIVATE_ONLY_MSG)
            return
        await self.panel.send(update.get_bot(), chat.id, user.id, name, arg, self.A)
        await self.after_view(update, name)

    # ---------- comandos ----------
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self.blocked_by_risk(update):
            return
        if not self.is_private(update):
            await send_text(update.effective_message, "¡Quiubo! Soy NEXUS-IA 🎮 Escríbeme por privado para el menú completo.\n\n" + HELP)
            return
        await self.welcome(update)

    async def welcome(self, update: Update) -> None:
        bot, chat = update.get_bot(), update.effective_chat.id
        kb = main_keyboard() if self.s.main_keyboard_enabled else None
        text = "🤖 Encendiendo a NEXUS-IA…"
        msg = None
        if self.s.welcome_anim_enabled:
            try:
                msg = await _retry(bot.send_message, chat_id=chat, text=text, reply_markup=kb,
                                   message_effect_id=CONFETTI_EFFECT_ID)
            except TelegramError as e:        # Telegram rechazo el efecto: reenvio sin efecto
                log.info("efecto de confeti rechazado (%s); reenvio sin efecto", type(e).__name__)
                msg = await send_text(bot, text, chat_id=chat, reply_markup=kb)
            for step in ("🎮 Cargando juegos…", "💸 Revisando ofertas…", "✨ ¡Listo, parcero!"):
                await asyncio.sleep(0.6)
                await safe_edit(msg, step)
        elif kb is not None:
            await send_text(bot, "¡Quiubo, parcero! 🎮", chat_id=chat, reply_markup=kb)
        if self.s.main_panel_enabled:
            await self.panel.send(bot, chat, update.effective_user.id, "menu", "", self.A)
        else:
            await send_text(bot, HELP, chat_id=chat)

    async def cmd_menu(self, update, ctx) -> None:
        if await self.blocked_by_risk(update):
            return
        await self.open_view(update, "menu")

    def view_cmd(self, name: str):
        async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if await self.blocked_by_risk(update):
                return
            await self.open_view(update, name)
        return handler

    async def cmd_help(self, update, ctx) -> None:
        if await self.blocked_by_risk(update):
            return
        await send_text(update.effective_message, HELP)

    async def cmd_gratis(self, update, ctx) -> None:
        if await self.blocked_by_risk(update):
            return
        r = await self.pipe.free_today()
        await send_text(update.effective_message, r.text)
        await self.after_view(update, "free")

    async def cmd_estado(self, update, ctx) -> None:
        if await self.blocked_by_risk(update):
            return
        b = self.A["budget"]
        pct = 100 * b.remaining() // b.daily if b.enabled and b.daily else 100
        await send_text(update.effective_message, f"✅ <b>NEXUS-IA activo</b>\n🧠 Cupo de IA de hoy: {pct}% disponible")

    async def cmd_reset(self, update, ctx) -> None:
        self.A["orch"].reset(str(update.effective_user.id))
        await send_text(update.effective_message, "Listo, empezamos de cero 🧹")

    async def cmd_hide_keyboard(self, update, ctx) -> None:
        await update.effective_message.reply_text("Teclado oculto 🙈 Con /menu o /start lo vuelves a ver.",
                                                  reply_markup=ReplyKeyboardRemove())

    async def cmd_delete_data(self, update, ctx) -> None:
        if await self.blocked_by_risk(update):
            return
        uid = update.effective_user.id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Sí, borrar todo", callback_data=cbm.make("bx", uid)),
                                    InlineKeyboardButton("Cancelar", callback_data=cbm.make("bn", uid))]])
        await send_text(update.effective_message, "¿Seguro? Voy a borrar todo lo que tengo de ti: perfil, XP, gustos, historial. No se puede deshacer.", reply_markup=kb)

    def erase_user(self, uid: int) -> None:
        self.A["orch"].reset(str(uid))
        self.last.clear_user(uid)
        self.A["budget"].forget_user(str(uid))
        for fn in self.erasers:
            try:
                fn(uid)
            except Exception:
                log.exception("borrado parcial fallo")

    # ---------- texto ----------
    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_private(update):
            return                               # en grupos solo comandos
        msg, uid = update.effective_message, update.effective_user.id
        text = msg.text or ""
        v = self.safety.check(uid, text)         # PRIORIDAD ABSOLUTA
        if v.kind in ("risk", "released"):
            await send_text(msg, v.text)
            return
        await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        if v.kind == "guard":
            await send_text(msg, await self.safety.guard_reply(uid, text))
            return
        view = label_to_view(text) if self.s.main_keyboard_enabled else None
        if view:                                  # teclado fijo: antes del orquestador, sin gastar cupo
            await self.open_view(update, view)
            return
        reply = await self.pipe.handle(str(uid), text)
        await self.deliver(update, reply)

    async def deliver(self, update: Update, reply) -> None:
        chat, uid = update.effective_chat.id, update.effective_user.id
        if self.s.cards_enabled:
            await send_reply(update.get_bot(), chat, uid, reply, self.last, private=self.is_private(update))
        else:
            await send_text(update.get_bot(), reply.text, chat_id=chat)
        st = self.A.get("store")
        if st and reply.kind in ("games", "sheet", "compare") and reply.games:   # busqueda real: XP con tope diario
            await self.announce(update.get_bot(), chat, st.on_search(uid))

    # ---------- botones ----------
    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        uid = q.from_user.id
        cb = cbm.parse(q.data)
        err = cbm.check(cb, uid)
        if err:
            await q.answer(err, show_alert=True)
            return
        if await self.blocked_by_risk(update):
            return
        assert cb is not None
        chat = q.message.chat_id
        bot = q.get_bot()
        await q.answer()
        try:
            if cb.action == "v":
                if not await self.panel.edit(q.message, uid, cb.arg, "", self.A):
                    await self.panel.send(bot, chat, uid, cb.arg, "", self.A)
                await self.after_view(update, cb.arg)
            elif cb.action == "fa":
                full = self.last.get_full(uid, chat)
                await send_text(bot, full or cbm.EXPIRED_MSG, chat_id=chat)
            elif cb.action == "rc":
                f = Filters(tags={cb.arg}) if cb.arg in RC_TAGS else Filters(genres={cb.arg})
                await bot.send_chat_action(chat, ChatAction.TYPING)
                await self.deliver(update, await self.pipe.recommend(str(uid), f))
            elif cb.action == "bd":
                amount = Amount(float(cb.arg[1:]), "COP" if cb.arg[0] == "c" else "USD")
                await bot.send_chat_action(chat, ChatAction.TYPING)
                await self.deliver(update, await self.pipe.recommend(str(uid), Filters(amount=amount)))
            elif cb.action in ("fx", "sm", "cp"):
                await self.on_game_button(update, cb)
            elif cb.action == "kb":
                await bot.send_message(chat, "Teclado listo ⌨️", reply_markup=main_keyboard())
            elif cb.action == "bx":
                self.erase_user(uid)
                await safe_edit(q.message, "Listo, borré todo lo tuyo 🧹")
            elif cb.action == "bn":
                await safe_edit(q.message, "Tranquilo, no borré nada 👍")
            elif cb.action in self.extra_cb:
                await self.extra_cb[cb.action](self, update, cb)
        except TelegramError as e:
            log.warning("callback %s fallo (%s)", cb.action, type(e).__name__)

    async def on_game_button(self, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        uid, chat, bot = q.from_user.id, q.message.chat_id, q.get_bot()
        lr = self.last.get(uid, chat)
        try:
            idx = int(cb.arg)
        except ValueError:
            idx = -1
        if not lr or not (0 <= idx < len(lr.games)):
            await send_text(bot, cbm.EXPIRED_MSG, chat_id=chat)
            return
        g = lr.games[idx]
        if cb.action == "fx":
            if not g.reason:
                g.reason = build_reason(g)
            rows = [[InlineKeyboardButton("🛒 Ver oferta", url=g.deal_url)]] if g.deal_url else []
            await send_text(bot, render_sheet(g, lr.trm), chat_id=chat,
                            reply_markup=InlineKeyboardMarkup(rows) if rows else None)
        elif cb.action == "sm":
            await bot.send_chat_action(chat, ChatAction.TYPING)
            sims = self.svc.similar(g)[:3]
            games = [x for x in await asyncio.gather(*(self.svc.get_game(c["title"], c.get("appid")) for c in sims)) if x]
            if not games:
                await send_text(bot, "No tengo parecidos curados para ese todavía 🤷", chat_id=chat)
                return
            self.last.save(uid, chat, "similar", games, lr.trm)
            await send_text(bot, f"🔁 Parecidos a <b>{esc(g.title)}</b>:", chat_id=chat)
            for i, x in enumerate(games):
                await send_card(bot, chat, uid, i, x, lr.trm)
        elif cb.action == "cp":
            other = lr.games[(idx + 1) % len(lr.games)] if len(lr.games) > 1 else None
            if other is None:
                sims = self.svc.similar(g)[:1]
                other = await self.svc.get_game(sims[0]["title"], sims[0].get("appid")) if sims else None
            if other is None:
                await send_text(bot, "No tengo con qué compararlo ahorita 🤷", chat_id=chat)
                return
            r = self.pipe.compare_objs(g, other, lr.trm)
            await send_text(bot, r.text, chat_id=chat)

    async def on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("error en handler: %s", type(ctx.error).__name__)       # nunca el contenido del mensaje
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text("Uy, se me cruzaron los cables. Intenta de nuevo 🙏")
        except Exception:
            pass
