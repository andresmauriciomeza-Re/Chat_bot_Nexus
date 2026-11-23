from types import SimpleNamespace as NS

import httpx

from app.bot.inline import RateLimiter, desc_line, install_inline
from app.features.install import install_features
from app.voice.install import install_voice
from app.voice.tts import TTS

from .test_games import handler as base_handler
from .test_games import make_service
from .test_ui import FakeBot, make_handlers, upd

DEALS = [{"title": "Hades", "salePrice": "12.49", "normalPrice": "24.99", "savings": "50.0", "dealID": "A1",
          "steamAppID": "1145360", "gameID": "196149", "thumb": "https://t/x.jpg"},
         {"title": "Hades", "salePrice": "12.49", "normalPrice": "24.99", "savings": "50.0", "dealID": "A2",
          "steamAppID": "1145360", "gameID": "196149", "thumb": "https://t/x.jpg"},
         {"title": "Hades II <b>", "salePrice": "29.99", "normalPrice": "29.99", "savings": "0", "dealID": "B1",
          "steamAppID": "1", "gameID": "9", "thumb": "http://insegura/x.jpg"}]


def inline_handler(req: httpx.Request):
    if "cheapshark.com/api/1.0/deals" in str(req.url):
        return httpx.Response(200, json=DEALS)
    return base_handler(req)


class IQ:
    def __init__(self, query, uid=7):
        self.query, self.from_user, self.answers = query, NS(id=uid), []

    async def answer(self, results, **kw):
        self.answers.append((results, kw))


def setup(tmp_path, **kw):
    h, A = make_handlers(tmp_path, **kw)
    h.svc = A["svc"] = make_service(inline_handler)
    install_features(A, h)
    install_voice(NS(add_handler=lambda *a: None), h, TTS(ffmpeg=None))
    handlers = []
    install_inline(NS(add_handler=handlers.append), h)
    return h, A, handlers


async def test_inline_results_dedupe_limit_and_escape(tmp_path):
    h, A, handlers = setup(tmp_path, inline_max_results=2)
    assert len(handlers) == 1
    q = IQ("hades")
    await h.on_inline(NS(inline_query=q), NS())
    results, kw = q.answers[0]
    assert [r.title for r in results] == ["Hades", "Hades II <b>"] and len(results) <= 2
    assert "&lt;b&gt;" in results[1].input_message_content.message_text
    assert "CheapShark" in results[0].input_message_content.message_text
    assert results[0].thumbnail_url and results[1].thumbnail_url is None       # solo https
    assert kw["cache_time"] > 0 and kw["button"].start_parameter == "inline"
    assert "USD 12.49" in results[0].description and "COP" in results[0].description


async def test_inline_empty_short_risky_ratelimit_flag(tmp_path):
    h, A, _ = setup(tmp_path, inline_rate_per_min=2)
    for text in ("a", "", "me quiero morir"):
        q = IQ(text)
        await h.on_inline(NS(inline_query=q), NS())
        assert q.answers[0][0] == []
    q1, q2, q3 = IQ("hades"), IQ("hades"), IQ("hades")
    for q in (q1, q2, q3):
        await h.on_inline(NS(inline_query=q), NS())
    assert q1.answers[0][0] and q2.answers[0][0] and q3.answers[0][0] == []     # limite por minuto
    h2, A2, handlers = setup(tmp_path / "x", inline_enabled=False)
    assert handlers == []


async def test_inline_degrades_when_source_down(tmp_path):
    h, A, _ = setup(tmp_path)

    def down(req):
        raise httpx.ConnectError("x")
    h.svc.http._client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    h.svc.http.retries = 0
    q = IQ("hades")
    await h.on_inline(NS(inline_query=q), NS())
    assert q.answers[0][0] == []


def test_rate_limiter_window():
    t = [0.0]
    r = RateLimiter(2, clock=lambda: t[0])
    assert r.allow(1) and r.allow(1) and not r.allow(1) and r.allow(2)
    t[0] = 61
    assert r.allow(1)


def test_desc_line():
    from app.sources.models import GameInfo
    assert "Gratis" in desc_line(GameInfo("x", sale_usd=0.0), 4000)
    assert desc_line(GameInfo("x"), 4000) == "Sin precio ahora"


async def test_estado_and_maintenance(tmp_path):
    h, A, _ = setup(tmp_path)
    bot = FakeBot()
    u, m = upd("/estado", bot=bot)
    await h.cmd_estado(u, NS(bot=bot))
    txt = m.sent[0][0]
    assert "CheapShark" in txt and "Steam" in txt and "Epic" in txt and "TRM" in txt and "Cupo de IA" in txt
    # mantenimiento: todo se frena salvo /estado, /help y el riesgo emocional
    h.s.maintenance_mode = True
    u, m = upd("/menu", bot=bot)
    await h.cmd_menu(u, NS(bot=bot))
    assert "mantenimiento" in m.sent[0][0]
    u, m = upd("hola", bot=bot)
    await h.on_text(u, NS(bot=bot))
    assert "mantenimiento" in m.sent[0][0]
    u, m = upd("me quiero morir", bot=bot)
    await h.on_text(u, NS(bot=bot))
    assert "123" in m.sent[0][0]                                        # riesgo manda siempre
    u, m = upd("/estado", uid=8, bot=bot)
    await h.cmd_estado(u, NS(bot=bot))
    assert "En mantenimiento" in m.sent[0][0]
    q = IQ("hades", uid=9)
    await h.on_inline(NS(inline_query=q), NS())
    assert q.answers[0][0] == []


async def test_health_marks_disabled_and_down(tmp_path):
    h, A, _ = setup(tmp_path)
    h.svc.enabled["epic"] = False
    res = await h.svc.health()
    assert res["Epic"] is None and res["CheapShark"] is True


async def test_similar_intent_and_buttons_data(tmp_path):
    h, A, _ = setup(tmp_path)
    h.svc.catalog = [{"title": "Hades", "genres": ["accion", "roguelike"], "tags": ["corto"], "platforms": ["pc"]},
                     {"title": "Hades", "genres": ["accion", "roguelike"], "tags": ["corto"], "platforms": ["pc"]}]
    r = await h.pipe.handle("u", "juegos parecidos a Hades")
    assert r.kind in ("games", "info")
