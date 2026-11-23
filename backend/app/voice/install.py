"""Instala Fase 5: notas de voz de entrada (Groq whisper) y respuestas en voz (edge-tts)."""
from __future__ import annotations

import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ..bot import callbacks as cbm
from ..bot.panel import View, ViewCtx
from ..bot.send import send_text
from ..core.orchestrator import MSG_COOLDOWN, MSG_DOWN, MSG_QUOTA_GLOBAL, MSG_QUOTA_USER
from ..llm.base import LLMError
from ..llm.budget import LLMBudgetError
from .tts import TTS, VOICES, clean_for_speech

log = logging.getLogger(__name__)
MAX_VOICE_BYTES = 5 * 1024 * 1024
PRIVACY = ("🔒 <b>Aviso de privacidad</b>\nPara pasar el texto a voz lo envío a un servicio de Microsoft (Edge TTS). "
           "Solo viaja el texto de esta respuesta: no mando tu nombre ni tu usuario y yo no guardo audios. "
           "Si prefieres que no, simplemente no uses 🔊.")
VOICE_NAMES = {"salome": "Salomé 👩", "gonzalo": "Gonzalo 👨"}


def install_voice(app: Application, h, tts: TTS | None = None) -> None:
    A, s = h.A, h.s
    store, last, safety = A["store"], A["last"], A["safety"]
    tts = tts or TTS()
    A["tts"] = tts

    def voice_key(uid: int) -> str:
        return "gonzalo" if store.get_flag(uid, "voice_male") else "salome"

    # ---------- salida: boton 🔊 Escuchar ----------
    def listen_markup(uid: int, chat: int, text: str):
        if not (s.voice_out_enabled and store.ok) or safety.active(uid):      # con riesgo: sin voz
            return None
        speech = clean_for_speech(text)
        if len(speech) < 3:
            return None
        last.save_speech(uid, chat, speech)
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔊 Escuchar", callback_data=cbm.make("tts", uid))]])
    h.listen_markup = listen_markup

    async def speak(bot, uid: int, chat: int) -> None:
        if safety.active(uid):
            return
        text = last.get_speech(uid, chat)
        if not text:
            await send_text(bot, cbm.EXPIRED_MSG, chat_id=chat)
            return
        if store.voice_used(uid) >= s.voice_daily_limit:
            await send_text(bot, f"Ya usaste tus {s.voice_daily_limit} audios de hoy 🎧. Mañana se renuevan.", chat_id=chat)
            return
        await bot.send_chat_action(chat, ChatAction.RECORD_VOICE)
        res = await tts.speak(text, voice_key(uid))
        if not res:
            await send_text(bot, "No pude armar el audio ahorita 😅. Inténtalo más tarde.", chat_id=chat)
            return
        data, kind = res
        try:
            if kind == "ogg":
                await bot.send_voice(chat_id=chat, voice=io.BytesIO(data))
            else:
                try:
                    await bot.send_voice(chat_id=chat, voice=io.BytesIO(data))
                except TelegramError:
                    await bot.send_audio(chat_id=chat, audio=io.BytesIO(data), filename="nexus.mp3", title="NEXUS-IA")
        except TelegramError as e:
            log.warning("no se pudo enviar la voz (%s)", type(e).__name__)
            await send_text(bot, "No pude enviarte el audio 😅.", chat_id=chat)
            return
        store.voice_use(uid)

    async def a_listen(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        uid, chat, bot = q.from_user.id, q.message.chat_id, q.get_bot()
        if not s.voice_out_enabled:
            await send_text(bot, "La voz está apagada por ahora 🔇", chat_id=chat)
            return
        if not store.get_flag(uid, "voice_ok"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Entendido, escuchar 🔊", callback_data=cbm.make("ta", uid))]])
            await send_text(bot, PRIVACY, chat_id=chat, reply_markup=kb)
            return
        await speak(bot, uid, chat)

    async def a_accept(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        store.set_flag(q.from_user.id, "voice_ok", True)
        await speak(q.get_bot(), q.from_user.id, q.message.chat_id)

    async def a_voice_choice(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        if cb.arg in VOICES:
            store.set_flag(q.from_user.id, "voice_male", cb.arg == "gonzalo")
            await A["panel"].edit(q.message, q.from_user.id, "settings", "", A)

    # ---------- ajustes ----------
    async def v_settings(ctx: ViewCtx) -> View:
        on = lambda b: "✅" if b else "⬜"  # noqa: E731
        vk = voice_key(ctx.user_id)
        lines = ["🔊 <b>Voz y ajustes</b>",
                 f"{on(s.main_keyboard_enabled)} Teclado fijo · {on(s.mascot_anim_enabled)} Mascota animada",
                 f"{on(s.voice_in_enabled)} Entiendo notas de voz (hasta {s.voice_max_seconds} s)",
                 f"{on(s.voice_out_enabled)} Respondo en voz con el botón 🔊 ({tts.format_name})"]
        if s.voice_out_enabled:
            lines.append(f"Voz: <b>{VOICE_NAMES[vk]}</b> · hoy {store.voice_used(ctx.user_id)}/{s.voice_daily_limit} audios")
        rows = []
        if s.voice_out_enabled:
            rows.append([InlineKeyboardButton(("✅ " if vk == k else "") + n, callback_data=cbm.make("vs", ctx.user_id, k))
                         for k, n in VOICE_NAMES.items()])
        rows.append([InlineKeyboardButton("⌨️ Mostrar teclado", callback_data=cbm.make("kb", ctx.user_id))])
        return View("\n".join(lines), "sleepy", rows)
    A["panel"].register("settings", v_settings)

    # ---------- entrada: nota de voz ----------
    async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not h.is_private(update):
            return
        msg, uid = update.effective_message, update.effective_user.id
        v = msg.voice
        if v is None:
            return
        if (v.duration or 0) > s.voice_max_seconds or (v.file_size or 0) > MAX_VOICE_BYTES:
            await send_text(msg, f"Esa nota es muy larga 😅. Máximo {s.voice_max_seconds} segundos, o escríbeme.")
            return
        await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        try:
            data = bytes(await (await v.get_file()).download_as_bytearray())
        except TelegramError:
            await send_text(msg, "No pude bajar tu nota de voz 😅. ¿Me la mandas de nuevo o me escribes?")
            return
        try:
            text = await A["llm"].transcribe(data, user=str(uid), filename="voice.ogg", model=s.voice_stt_model)
        except LLMBudgetError as e:
            await send_text(msg, {"user": MSG_QUOTA_USER, "global": MSG_QUOTA_GLOBAL}.get(e.reason, MSG_COOLDOWN)
                            + "\nMientras tanto escríbeme y te ayudo ✍️")
            return
        except LLMError:
            await send_text(msg, MSG_DOWN + "\nPuedes escribirme en vez de mandar audio ✍️")
            return
        if not text.strip():
            await send_text(msg, "No te entendí bien 🙈. ¿Me repites o me escribes?")
            return
        await h.process_text(update, ctx, text, echo=True)

    if s.voice_in_enabled:
        app.add_handler(MessageHandler(filters.VOICE, on_voice))
    h.extra_cb.update({"tts": a_listen, "ta": a_accept, "vs": a_voice_choice})
