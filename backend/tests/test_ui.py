import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from telegram.error import BadRequest, RetryAfter

from app.bot import callbacks as cbm
from app.bot import send as send_mod
from app.bot.app import COMMANDS, build_application, build_services
from app.bot.cards import card_markup, send_card
from app.bot.handlers import CONFETTI_EFFECT_ID, BotHandlers
from app.bot.keyboard import LABELS, main_keyboard
from app.bot.mascot import MAX_BYTES, Mascot
from app.bot.panel import FOOTER_LIMIT, GRID, fit_footer
from app.bot.views import register_base_views
from app.config import Settings
from app.core.safety import GUARD_SOFT
from app.games.pipeline import Reply
from app.sources.models import GameInfo
from app.tools.last_result import LastResults


# ---------- fakes ----------
class FakeMsg:
    def __init__(self, text="", chat_id=1, bot=None):
        self.text, self.chat_id, self.sent, self.edits, self.bot = text, chat_id, [], [], bot
        self.photo = self.animation = self.video = None

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return FakeMsg(text, self.chat_id)

    async def edit_text(self, text, **kw):
        self.edits.append(text)
        return self

    def get_bot(self):
        return self.bot


class FakeBot:
    def __init__(self, fail_effect=False, fail_photo=False):
        self.calls, self.fail_effect, self.fail_photo = [], fail_effect, fail_photo

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("msg", text, kw))
        if self.fail_effect and "message_effect_id" in kw:
            raise BadRequest("Message effect is invalid")
        return FakeMsg(text, chat_id)

    async def send_photo(self, chat_id, photo, **kw):
        self.calls.append(("photo", photo, kw))
        if self.fail_photo:
            raise BadRequest("wrong file identifier/HTTP URL specified")
        return FakeMsg("", chat_id)

    async def send_animation(self, chat_id, animation, **kw):
        self.calls.append(("anim", animation, kw))
        return NS(animation=NS(file_id="FID-ANIM"), photo=None)

    async def send_chat_action(self, *a, **k):
        self.calls.append(("action",))

    def __getattr__(self, n):
        raise AttributeError(n)


def settings(tmp_path, **kw):
    return Settings(_env_file=None, telegram_bot_token="123456:" + "a" * 30, groq_api_key="k" * 12,
                    groq_model="m", data_dir=str(tmp_path), **kw)


def make_handlers(tmp_path, **kw):
    s = settings(tmp_path, **kw)
    A = build_services(s)
    A["mascot"].assets.clear()                  # los tests no dependen de los archivos reales de la mascota
    register_base_views(A["panel"])
    return BotHandlers(A, A["panel"]), A


def upd(text="", uid=7, chat=1, ctype="private", bot=None):
    msg = FakeMsg(text, chat, bot)
    return NS(effective_chat=NS(id=chat, type=ctype), effective_user=NS(id=uid), effective_message=msg,
              callback_query=None, get_bot=lambda: bot), msg


# ---------- botones ----------
def test_callback_ownership_and_expiry():
    t = [1_000_000.0]
    clk = lambda: t[0]  # noqa: E731
    d = cbm.make("v", 7, "menu", clock=clk)
    cb = cbm.parse(d)
    assert len(d.encode()) <= 64 and cb.owner == 7 and cb.arg == "menu"
    assert cbm.check(cb, 7, clock=clk) is None
    assert "otra persona" in cbm.check(cb, 8, clock=clk)
    t[0] += 2 * 3600 - 120
    assert cbm.check(cb, 7, clock=clk) is None                     # panel: vive 2 h
    t[0] += 400
    assert "/menu" in cbm.check(cb, 7, clock=clk)
    t[0] = 1_000_000.0
    r = cbm.parse(cbm.make("fx", 7, "0", clock=clk))
    t[0] += 31 * 60
    assert "/menu" in cbm.check(r, 7, clock=clk)                    # resultados: 30 min
    assert cbm.check(cbm.parse("basura"), 7)


def test_last_results_expire():
    t = [0.0]
    lr = LastResults(clock=lambda: t[0])
    lr.save(1, 2, "recs", [GameInfo("A")])
    assert lr.get(1, 2).games[0].title == "A" and lr.get(1, 3) is None
    t[0] = 31 * 60
    assert lr.get(1, 2) is None
    lr.save_full(1, 2, "x")
    assert lr.get_full(1, 2) == "x"


def test_fit_footer_limits():
    text = "\n".join(f"<b>línea {i}</b> " + "x" * 50 for i in range(60))
    short, cut = fit_footer(text)
    assert cut and len(short) <= FOOTER_LIMIT and short.count("<b>") == short.count("</b>")
    assert fit_footer("corto") == ("corto", False)


# ---------- envio seguro ----------
async def test_safe_edit_not_modified_and_retry_after(monkeypatch):
    async def nosleep(_): pass
    monkeypatch.setattr(send_mod.asyncio, "sleep", nosleep)

    class M:
        n = 0
        async def edit_text(self, text, **kw):
            M.n += 1
            if M.n == 1:
                raise RetryAfter(1)
            raise BadRequest("Message is not modified: specified new message content")
    assert await send_mod.safe_edit(M(), "x") is True and M.n == 2


async def test_send_text_html_fallback_to_plain():
    calls = []

    class Msg:
        async def reply_text(self, text, **kw):
            calls.append((text, kw.get("parse_mode")))
            if kw.get("parse_mode"):
                raise BadRequest("Can't parse entities")
    await send_mod.send_text(Msg(), "<b>hola</b> &amp; adiós")
    assert calls[1] == ("hola & adiós", None)


# ---------- mascota ----------
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 20


def test_mascot_priority_and_validation(tmp_path):
    (tmp_path / "welcome.png").write_bytes(PNG)
    (tmp_path / "happy.png").write_bytes(PNG)
    (tmp_path / "happy.mp4").write_bytes(MP4)                  # animacion gana
    (tmp_path / "sad.png").write_bytes(b"no soy un png")       # corrupto: se ignora
    (tmp_path / "angry.png").write_bytes(b"")                   # vacio
    big = tmp_path / "gift.gif"
    big.write_bytes(b"GIF89a" + b"0" * (MAX_BYTES + 10))        # > 10 MB
    m = Mascot(tmp_path)
    assert m.resolve("happy").kind == "animation"
    assert m.resolve("sad").name == "welcome"                   # cae a welcome
    assert "angry" not in m.assets and "gift" not in m.assets
    assert Mascot(tmp_path / "nada").resolve("welcome") is None  # sin archivos: texto
    assert Mascot(tmp_path, anim_enabled=False).resolve("happy").kind == "photo"


async def test_mascot_uploads_once_and_reuses_file_id(tmp_path):
    (tmp_path / "happy.mp4").write_bytes(MP4)
    m = Mascot(tmp_path, store_path=tmp_path / "ids.json")
    bot = FakeBot()
    await m.send(bot, 1, "happy", "hola")
    await m.send(bot, 1, "happy", "hola")
    assert bot.calls[0][0] == "anim" and not isinstance(bot.calls[0][1], str)
    assert bot.calls[1][1] == "FID-ANIM"                          # segunda vez: file_id
    assert "FID-ANIM" in (tmp_path / "ids.json").read_text()
    assert await Mascot(tmp_path / "x").send(bot, 1, "happy", "x") is None


# ---------- tarjetas ----------
def big_game():
    return GameInfo("T" * 200, image="https://img/x.jpg", sale_usd=10, normal_usd=20, discount_pct=50,
                    price_cop=40000, historic_low_usd=5, deal_url="https://deal/x", reason="r" * 2000, store_name="S")


async def test_card_caption_limit_and_buttons():
    bot = FakeBot()
    await send_card(bot, 1, 7, 0, big_game(), 4000)
    kind, photo, kw = bot.calls[0]
    assert kind == "photo" and len(kw["caption"]) <= 1024
    labels = [b.text for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "📖 Ficha" in labels and "🛒 Ver oferta" in labels and "🔁 Similares" in labels and "⚖️ Comparar" in labels


async def test_card_falls_back_to_text_when_photo_fails():
    bot = FakeBot(fail_photo=True)
    await send_card(bot, 1, 7, 0, big_game(), 4000)
    assert bot.calls[-1][0] == "msg" and len(bot.calls[-1][1]) <= 4096


def test_html_escape_in_cards():
    from app.games.render import render_game
    assert "<script>" not in render_game(GameInfo("<script>alert(1)</script>"), 4000)


# ---------- handlers ----------
async def test_welcome_effect_fallback_and_keyboard(tmp_path):
    h, _ = make_handlers(tmp_path)
    bot = FakeBot(fail_effect=True)
    u, _m = upd("/start", bot=bot)
    h.panel.mascot.assets.clear()
    await h.cmd_start(u, NS(bot=bot))
    msgs = [c for c in bot.calls if c[0] == "msg"]
    assert msgs[0][2].get("message_effect_id") == CONFETTI_EFFECT_ID           # primero con efecto
    assert "message_effect_id" not in msgs[1][2] and msgs[1][2]["reply_markup"] is not None   # reenvio sin efecto
    assert any("NEXUS-IA" in c[1] for c in msgs) and len(msgs) >= 3             # luego el panel (texto: sin mascota)


async def test_keyboard_button_skips_orchestrator(tmp_path):
    h, _ = make_handlers(tmp_path)

    class Boom:
        async def handle(self, *a, **k):
            raise AssertionError("no debe gastar cupo")
    h.pipe = Boom()
    bot = FakeBot()
    for label in LABELS:
        u, _m = upd(label, bot=bot)
        await h.on_text(u, NS(bot=bot))
    assert sum(1 for c in bot.calls if c[0] == "msg") == len(LABELS)


async def test_risk_beats_keyboard_and_commands(tmp_path):
    h, _ = make_handlers(tmp_path)
    bot = FakeBot()
    u, m = upd("me quiero morir", bot=bot)
    await h.on_text(u, NS(bot=bot))
    assert "123" in m.sent[0][0] and "106" in m.sent[0][0] and not bot.calls
    u2, m2 = upd("🎮 Recomiéndame", bot=bot)             # boton del teclado durante la guardia: solo apoyo
    await h.on_text(u2, NS(bot=bot))
    assert not [c for c in bot.calls if c[0] in ("photo", "anim")]
    u3, m3 = upd("/menu", bot=bot)
    await h.cmd_menu(u3, NS(bot=bot))
    assert m3.sent[0][0] == GUARD_SOFT                     # sin panel ni mascota


async def test_groups_are_simple(tmp_path):
    h, _ = make_handlers(tmp_path)
    bot = FakeBot()
    u, m = upd("hola", ctype="supergroup", bot=bot)
    await h.on_text(u, NS(bot=bot))
    assert not m.sent and not bot.calls
    u, m = upd("/menu", ctype="supergroup", bot=bot)
    await h.cmd_menu(u, NS(bot=bot))
    assert "privado" in m.sent[0][0] and not bot.calls


async def test_callback_validation_in_handler(tmp_path):
    h, _ = make_handlers(tmp_path)
    answers = []

    class Q:
        data = cbm.make("v", 7, "menu")
        from_user = NS(id=99)                               # NO es el dueno
        message = NS(chat_id=1)
        async def answer(self, text=None, show_alert=False):
            answers.append((text, show_alert))
    u = NS(callback_query=Q(), effective_user=NS(id=99), effective_chat=NS(id=1, type="private"))
    await h.on_callback(u, NS(bot=FakeBot()))
    assert answers == [(cbm.NOT_OWNER_MSG, True)]


async def test_panel_edit_text_message_and_menu_button(tmp_path):
    h, A = make_handlers(tmp_path)
    msg = FakeMsg("menu", 1)
    ok = await A["panel"].edit(msg, 7, "help", "", A)
    assert ok and msg.edits
    # todo boton de vista trae «⬅️ Menú»; la cuadricula tiene los 11 botones pedidos + 💡 Consejo
    ctx = NS(user_id=7, chat_id=1, arg="", app=A)
    view = await A["panel"].build("help", ctx)
    _, markup = A["panel"].view_markup("help", view, ctx)
    assert "⬅️ Menú" in [b.text for r in markup.inline_keyboard for b in r]
    labels = [b.text for r in A["panel"].menu_markup(7).inline_keyboard for b in r]
    assert len(labels) == 12 and "🧠 Trivia" in labels and "🔊 Voz y ajustes" in labels and "💡 Consejo de NEXUS" in labels


async def test_game_buttons_expired_message(tmp_path):
    h, A = make_handlers(tmp_path)
    bot = FakeBot()
    h.last.save(7, 1, "recs", [big_game()], 4000.0)
    sent = []

    class Q:
        data = cbm.make("fx", 7, "0")
        from_user = NS(id=7)
        message = NS(chat_id=1, get_bot=lambda: bot)
        async def answer(self, *a, **k): pass
        def get_bot(self): return bot
    u = NS(callback_query=Q(), effective_user=NS(id=7), effective_chat=NS(id=1, type="private"), get_bot=lambda: bot)
    await h.on_callback(u, NS(bot=bot))
    assert any("Ficha" in c[1] or "big" in c[1] or "T" * 10 in c[1] for c in bot.calls if c[0] == "msg")
    h.last.clear_user(7)
    await h.on_callback(u, NS(bot=bot))
    assert "/menu" in bot.calls[-1][1]


def test_application_builds_and_registers_commands(tmp_path):
    app = build_application(settings(tmp_path))
    names = {c for c, _ in COMMANDS}
    assert {"start", "menu", "help", "estado", "reset", "nexus", "animo", "gratis", "gustos", "trivia", "perfil",
            "cofre", "borrar_datos", "ajustes"} <= names
    registered = {c for hd in app.handlers[0] for c in getattr(hd, "commands", [])}
    assert names <= registered
    assert len(main_keyboard().keyboard) == 3 and len(GRID) == 6


def test_reply_summary_for_cards():
    assert Reply("games", "x", summary="s").summary == "s"
