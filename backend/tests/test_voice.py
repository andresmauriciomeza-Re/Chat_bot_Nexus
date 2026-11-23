import httpx
import pytest
from types import SimpleNamespace as NS
from telegram.error import BadRequest

from app.bot import callbacks as cbm
from app.features.install import install_features
from app.llm.base import LLMUnavailableError
from app.llm.budget import BudgetedLLM, LLMBudgetError, TokenBudget
from app.llm.groq_provider import GroqProvider
from app.voice.install import install_voice
from app.voice.tts import TTS, clean_for_speech

from .test_ui import FakeBot, FakeMsg, make_handlers, upd

MP3 = b"\xff\xf3d\x00" + b"0" * 50


# ---------- limpieza de texto ----------
def test_clean_for_speech():
    t = clean_for_speech("🎮 <b>Hades</b> &amp; Celeste\nmira https://x.com/y 💵 USD 10")
    assert "<" not in t and "http" not in t and "🎮" not in t and "&amp;" not in t and "Hades & Celeste" in t
    long = clean_for_speech("Frase corta. " * 200)
    assert len(long) <= 601 and long.endswith(".")


# ---------- TTS: ffmpeg opcional ----------
async def fake_synth(text, voice):
    fake_synth.last = (text, voice)
    return MP3


async def test_tts_mp3_when_no_ffmpeg_and_voices():
    t = TTS(fake_synth, ffmpeg=None)
    assert t.format_name == "MP3"
    assert await t.speak("Hola parcero", "salome") == (MP3, "mp3") and fake_synth.last[1] == "es-CO-SalomeNeural"
    await t.speak("Hola", "gonzalo")
    assert fake_synth.last[1] == "es-CO-GonzaloNeural"


async def test_tts_falls_back_to_mp3_when_ffmpeg_broken_or_synth_fails():
    t = TTS(fake_synth, ffmpeg="C:/no/existe/ffmpeg.exe")
    assert (await t.speak("Hola")) == (MP3, "mp3")

    async def boom(text, voice):
        raise RuntimeError("sin red")
    assert await TTS(boom, ffmpeg=None).speak("Hola") is None
    assert await TTS(fake_synth, ffmpeg=None).speak("😀") is None       # nada que leer


# ---------- STT por httpx real con transporte simulado ----------
def groq(handler):
    return GroqProvider("k" * 12, "m", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_transcribe_through_httpx():
    seen = {}

    def h(req: httpx.Request):
        seen["url"] = str(req.url)
        for k, v in req.headers.items():
            v.encode("ascii")
        seen["ct"] = req.headers["content-type"]
        seen["body"] = req.content
        return httpx.Response(200, json={"text": " hola nexus "})
    p = groq(h)
    assert await p.transcribe(b"OggS...", model="whisper-large-v3-turbo") == "hola nexus"
    assert seen["url"].endswith("/audio/transcriptions") and seen["ct"].startswith("multipart/form-data")
    assert b"whisper-large-v3-turbo" in seen["body"]
    with pytest.raises(LLMUnavailableError):
        await groq(lambda r: httpx.Response(500)).transcribe(b"x")


async def test_budgeted_transcribe_respects_quota():
    class Inner:
        async def transcribe(self, audio, **kw):
            return "ok"
    b = TokenBudget(True, daily_tokens=400, per_user_tokens=1000)
    llm = BudgetedLLM(Inner(), b)
    assert await llm.transcribe(b"x", user="u") == "ok"
    with pytest.raises(LLMBudgetError):
        await llm.transcribe(b"x", user="u")


# ---------- flujos ----------
class VBot(FakeBot):
    def __init__(self, fail_voice=False, **kw):
        super().__init__(**kw)
        self.fail_voice = fail_voice

    async def send_voice(self, chat_id, voice, **kw):
        self.calls.append(("voice", chat_id))
        if self.fail_voice:
            raise BadRequest("voice not allowed")
        return NS()

    async def send_audio(self, chat_id, audio, **kw):
        self.calls.append(("audio", chat_id))
        return NS()


def setup(tmp_path, ffmpeg=None, **kw):
    h, A = make_handlers(tmp_path, **kw)
    install_features(A, h)
    handlers = []
    install_voice(NS(add_handler=handlers.append), h, TTS(fake_synth, ffmpeg=ffmpeg))
    return h, A, handlers


def voice_update(text_by_llm, bot, duration=5, size=1000, uid=7):
    u, msg = upd("", uid=uid, bot=bot)

    async def dl():
        return bytearray(b"OggS")

    async def get_file():
        return NS(download_as_bytearray=dl)
    msg.voice = NS(duration=duration, file_size=size, get_file=get_file)
    return u, msg


async def test_voice_note_is_transcribed_and_answered(tmp_path):
    h, A, handlers = setup(tmp_path)
    assert len(handlers) == 1
    got = []

    class LLM:
        async def transcribe(self, audio, user=None, **kw):
            return "cuánto cuesta Hades"
    A["llm"] = LLM()

    async def fake_handle(user, text):
        got.append(text)
        from app.games.pipeline import Reply
        return Reply("info", "ok")
    h.pipe.handle = fake_handle
    bot = VBot()
    u, msg = voice_update("", bot)
    await handlers[0].callback(u, NS(bot=bot))
    assert got == ["cuánto cuesta Hades"] and "Te entendí" in msg.sent[0][0]


async def test_voice_risk_is_text_only_no_voice_no_echo(tmp_path):
    h, A, handlers = setup(tmp_path)

    class LLM:
        async def transcribe(self, *a, **k):
            return "me quiero morir"
    A["llm"] = LLM()
    bot = VBot()
    u, msg = voice_update("", bot)
    await handlers[0].callback(u, NS(bot=bot))
    assert "123" in msg.sent[0][0] and len(msg.sent) == 1 and not [c for c in bot.calls if c[0] in ("voice", "audio")]
    assert h.listen_markup(7, 1, "Un texto cualquiera largo") is None       # guardia: sin boton 🔊


async def test_voice_limits_and_errors(tmp_path):
    h, A, handlers = setup(tmp_path)
    bot = VBot()
    u, msg = voice_update("", bot, duration=600)
    await handlers[0].callback(u, NS(bot=bot))
    assert "muy larga" in msg.sent[0][0]

    class Quota:
        async def transcribe(self, *a, **k):
            raise LLMBudgetError("user")
    A["llm"] = Quota()
    u, msg = voice_update("", bot)
    await handlers[0].callback(u, NS(bot=bot))
    assert "escríbeme" in msg.sent[0][0].lower()

    class Empty:
        async def transcribe(self, *a, **k):
            return "  "
    A["llm"] = Empty()
    u, msg = voice_update("", bot)
    await handlers[0].callback(u, NS(bot=bot))
    assert "No te entendí" in msg.sent[0][0]


def tts_cb(action, uid=7, bot=None):
    msg = FakeMsg("x", 1)
    msg.get_bot = lambda: bot

    async def answer(*a, **k):
        pass
    q = NS(data=cbm.make(action, uid), from_user=NS(id=uid), message=msg, answer=answer, get_bot=lambda: bot)
    return NS(callback_query=q, effective_user=NS(id=uid), effective_chat=NS(id=1, type="private"), get_bot=lambda: bot)


async def test_listen_button_privacy_notice_limit_and_formats(tmp_path):
    h, A, _ = setup(tmp_path, voice_daily_limit=2)
    bot = VBot()
    assert h.listen_markup(7, 1, "ok") is None                      # muy corto
    mk = h.listen_markup(7, 1, "Te recomiendo Hades, un roguelike buenísimo.")
    assert mk.inline_keyboard[0][0].text == "🔊 Escuchar"
    await h.on_callback(tts_cb("tts", bot=bot), NS(bot=bot))        # 1ra vez: aviso de privacidad
    assert any("Aviso de privacidad" in c[1] for c in bot.calls if c[0] == "msg") and not any(c[0] == "voice" for c in bot.calls)
    await h.on_callback(tts_cb("ta", bot=bot), NS(bot=bot))         # acepta -> audio (MP3 sin ffmpeg)
    assert [c[0] for c in bot.calls].count("voice") == 1 and A["store"].voice_used(7) == 1
    await h.on_callback(tts_cb("tts", bot=bot), NS(bot=bot))
    await h.on_callback(tts_cb("tts", bot=bot), NS(bot=bot))        # 3er uso: limite diario (2)
    assert [c[0] for c in bot.calls].count("voice") == 2
    assert any("audios de hoy" in c[1] for c in bot.calls if c[0] == "msg")


async def test_mp3_falls_back_to_send_audio(tmp_path):
    h, A, _ = setup(tmp_path)
    A["store"].set_flag(7, "voice_ok", True)
    h.listen_markup(7, 1, "Un texto para escuchar con calma.")
    bot = VBot(fail_voice=True)
    await h.on_callback(tts_cb("tts", bot=bot), NS(bot=bot))
    assert ("audio", 1) in bot.calls


async def test_voice_choice_and_settings_view(tmp_path):
    h, A, _ = setup(tmp_path)
    bot = VBot()
    u = tts_cb("vs", bot=bot)
    u.callback_query.data = cbm.make("vs", 7, "gonzalo")

    async def edit_text(text, **kw):
        u.callback_query.message.edits.append(text)
    u.callback_query.message.edit_text = edit_text
    await h.on_callback(u, NS(bot=bot))
    assert A["store"].get_flag(7, "voice_male")
    view = await A["panel"].build("settings", NS(user_id=7, chat_id=1, arg="", app=A))
    assert "Gonzalo" in view.text and "MP3" in view.text
    assert any("✅ Gonzalo" in b.text for r in view.rows for b in r)


async def test_voice_out_flag_off(tmp_path):
    h, A, _ = setup(tmp_path, voice_out_enabled=False)
    assert h.listen_markup(7, 1, "Un texto largo para escuchar") is None
