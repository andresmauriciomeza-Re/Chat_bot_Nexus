"""Instala Fase 4: animo (RAM), gustos, trivia, XP/racha/cofre/logros/perfil (SQLite)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, Update

from ..bot import callbacks as cbm
from ..bot.panel import View, ViewCtx
from ..bot.send import safe_edit, send_text
from ..games.filters import GENRE_LABEL, Filters
from ..telegram_utils import esc
from .mood import MOODS, MoodStore
from .store import ACHIEVEMENTS, Events, Store
from .trivia import Trivia

log = logging.getLogger(__name__)
LIKE_GENRES = ["accion", "aventura", "rpg", "estrategia", "indie", "simulacion", "carreras", "deportes", "puzzle",
               "terror", "plataformas", "shooter", "roguelike", "supervivencia"]
OFF = "Esta función está apagada por ahora 💤"


def bar(xp: int, nxt: int | None, prev: int = 0) -> str:
    if nxt is None:
        return "▰▰▰▰▰▰▰▰▰▰ máximo"
    filled = max(0, min(10, int(10 * (xp - prev) / max(1, nxt - prev))))
    return "▰" * filled + "▱" * (10 - filled) + f" {xp}/{nxt} XP"


def achievements_text(keys: list[str]) -> str:
    return "\n".join(f"{ACHIEVEMENTS[k][1]} {ACHIEVEMENTS[k][0]}" for k in keys if k in ACHIEVEMENTS)


def install_features(A: dict, h) -> None:
    s = A["settings"]
    panel = A["panel"]
    store = Store(s.data_path() / "nexus.db", s.gamification_enabled, s.xp_daily_query_cap, s.xp_daily_trivia_cap)
    moods, trivia = MoodStore(), Trivia()
    A.update(store=store, moods=moods, trivia=trivia)
    answered: set[tuple[int, int]] = set()

    h.erasers += [store.delete_user, moods.clear, trivia.forget]
    if s.likes_enabled:
        A["pipe"].prefs = lambda user: set(store.likes(int(user)))

    async def announce(bot, chat: int, ev: Events) -> None:
        if ev.new and not A["safety"].active(chat):
            lines = [f"🏅 ¡Logro desbloqueado! {ACHIEVEMENTS[k][1]} <b>{ACHIEVEMENTS[k][0]}</b>" for k in ev.new if k in ACHIEVEMENTS]
            if lines:
                await send_text(bot, "\n".join(lines), chat_id=chat)
    h.announce = announce

    # ---------------- animo ----------------
    async def v_mood(ctx: ViewCtx) -> View:
        if not s.mood_enabled:
            return View(OFF, "sleepy")
        btns = [InlineKeyboardButton(m.label, callback_data=cbm.make("md", ctx.user_id, m.key)) for m in MOODS.values()]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        return View("😊 <b>¿Cómo andas hoy?</b>\nCuéntame y te recomiendo algo a tu medida. "
                    "<i>Solo lo recuerdo 2 horas y no se guarda en ningún lado.</i>", "relaxed", rows)

    async def v_mood_set(ctx: ViewCtx) -> View:
        m = MOODS.get(ctx.arg)
        if not m or not s.mood_enabled:
            return await v_mood(ctx)
        rows = [[InlineKeyboardButton("🎮 Recomiéndame algo así", callback_data=cbm.make("mr", ctx.user_id))]]
        return View(f"{m.label}\n{esc(m.phrase)}", m.mascot, rows)

    async def a_mood(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        if s.mood_enabled and moods.set(q.from_user.id, cb.arg):
            if not await panel.edit(q.message, q.from_user.id, "mood_set", cb.arg, A):
                await panel.send(q.get_bot(), q.message.chat_id, q.from_user.id, "mood_set", cb.arg, A)

    async def a_mood_reco(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        m = moods.get(q.from_user.id)
        if not m:
            await send_text(q.get_bot(), "Ya se me olvidó tu ánimo (pasaron 2 horas). Cuéntame de nuevo con /animo 😉", chat_id=q.message.chat_id)
            return
        await hh.deliver(update, await A["pipe"].recommend(str(q.from_user.id), m.filters()))

    # ---------------- gustos ----------------
    async def v_likes(ctx: ViewCtx) -> View:
        if not s.likes_enabled or not store.ok:
            return View(OFF, "sleepy")
        mine = set(store.likes(ctx.user_id))
        btns = [InlineKeyboardButton(("✅ " if g in mine else "") + GENRE_LABEL[g].capitalize(),
                                     callback_data=cbm.make("lk", ctx.user_id, g)) for g in LIKE_GENRES]
        rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
        txt = ("💜 <b>Mis gustos</b>\nMarca los géneros que te gustan y los uso cuando me pidas "
               "«recomiéndame algo» sin más detalles.")
        return View(txt, "happy", rows)

    async def a_like(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        if cb.arg in LIKE_GENRES and s.likes_enabled:
            _, new = store.toggle_like(q.from_user.id, cb.arg)
            await panel.edit(q.message, q.from_user.id, "likes", "", A)
            await announce(q.get_bot(), q.message.chat_id, Events(new=new))

    # ---------------- perfil / cofre ----------------
    async def v_profile(ctx: ViewCtx) -> View:
        if not s.gamification_enabled:
            return View(OFF, "sleepy")
        p = store.profile(ctx.user_id)
        if p is None:
            return View("Ahorita no puedo abrir tu perfil. Intenta más tarde 🙏", "sad")
        from .store import LEVELS
        prev = max([n for n, _ in LEVELS if n <= p.xp] or [0])
        lines = ["🏆 <b>Tu perfil</b>", f"Nivel: <b>{esc(p.level)}</b>", bar(p.xp, p.next_at, prev),
                 f"🔥 Racha: {p.streak} día(s)"]
        if p.likes:
            lines.append("💜 Gustos: " + ", ".join(GENRE_LABEL[g] for g in p.likes if g in GENRE_LABEL))
        lines.append("")
        lines.append("<b>Logros</b>\n" + (achievements_text(p.achievements) or "Aún ninguno. ¡Busca un juego para el primero!"))
        rows = [[InlineKeyboardButton("🎁 Cofre diario", callback_data=cbm.make("v", ctx.user_id, "chest"))]]
        return View("\n".join(lines), "trophy", rows)

    async def v_chest(ctx: ViewCtx) -> View:
        if not s.gamification_enabled:
            return View(OFF, "sleepy")
        if ctx.arg.startswith("open:"):
            return View(f"🎁 ¡Abriste el cofre! Ganaste <b>+{int(ctx.arg[5:])} XP</b> ✨\nVuelve mañana por otro.", "gift")
        if ctx.arg == "done" or not store.chest_available(ctx.user_id):
            return View("🎁 Ya abriste el cofre de hoy. Vuelve mañana (se reinicia a medianoche, hora Colombia) 😉", "sleepy")
        rows = [[InlineKeyboardButton("🎁 Abrir cofre", callback_data=cbm.make("ch", ctx.user_id))]]
        return View("🎁 <b>Cofre diario</b>\nTienes un cofre esperándote. ¿Lo abrimos?", "gift", rows)

    async def a_chest(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        ok, ev = store.open_chest(q.from_user.id)
        arg = f"open:{ev.xp}" if ok else "done"
        await panel.edit(q.message, q.from_user.id, "chest", arg, A)
        await announce(q.get_bot(), q.message.chat_id, ev)

    # ---------------- trivia ----------------
    async def v_trivia(ctx: ViewCtx) -> View:
        if not s.trivia_enabled or not trivia:
            return View(OFF, "sleepy")
        qid, q = trivia.pick(ctx.user_id)
        rows = [[InlineKeyboardButton(opt, callback_data=cbm.make("tq", ctx.user_id, f"{qid}:{i}"))]
                for i, opt in enumerate(q.options)]
        return View(f"🧠 <b>Trivia gamer</b>\n\n{esc(q.q)}", "quiz", rows)

    async def v_trivia_res(ctx: ViewCtx) -> View:
        try:
            qid, opt, xp = (int(x) for x in ctx.arg.split(":"))
        except ValueError:
            return await v_trivia(ctx)
        res = trivia.check(qid, opt)
        if res is None:
            return await v_trivia(ctx)
        ok, q = res
        head = "✅ <b>¡Correcto!</b>" if ok else f"❌ Casi. La respuesta era <b>{esc(q.options[q.answer])}</b>."
        extra = f"\n+{xp} XP ✨" if xp else ""
        rows = [[InlineKeyboardButton("🧠 Otra pregunta", callback_data=cbm.make("v", ctx.user_id, "trivia"))]]
        return View(f"{head}\n{esc(q.explain)}{extra}", "happy" if ok else "sad", rows)

    async def a_trivia(hh, update: Update, cb: cbm.CB) -> None:
        q = update.callback_query
        try:
            qid, opt = (int(x) for x in cb.arg.split(":"))
        except ValueError:
            return
        key = (q.from_user.id, q.message.message_id)
        res = trivia.check(qid, opt)
        if res is None:
            return
        xp, ev = 0, Events()
        if key not in answered:                       # una sola respuesta por pregunta
            answered.add(key)
            if len(answered) > 5000:
                answered.clear()
            ev = store.on_trivia(q.from_user.id, res[0])
            xp = ev.xp
        else:
            return
        await panel.edit(q.message, q.from_user.id, "trivia_res", f"{qid}:{opt}:{xp}", A)
        await announce(q.get_bot(), q.message.chat_id, ev)

    for name, fn in (("mood", v_mood), ("mood_set", v_mood_set), ("likes", v_likes), ("profile", v_profile),
                     ("chest", v_chest), ("trivia", v_trivia), ("trivia_res", v_trivia_res)):
        panel.register(name, fn)
    h.extra_cb.update({"md": a_mood, "mr": a_mood_reco, "lk": a_like, "ch": a_chest, "tq": a_trivia})
