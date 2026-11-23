import asyncio
import random
from types import SimpleNamespace as NS

import httpx

from app import personality as P
from app.bot.app import build_services
from app.bot.persona import install_persona
from app.bot.typing import with_typing
from app.features.install import install_features
from app.games.pipeline import GamePipeline
from app.sources.models import GameInfo

from .test_games import FakeLLM, handler as base_handler, make_service
from .test_ui import FakeBot, make_handlers, settings, upd, PNG

from app.core.orchestrator import Orchestrator


def test_small_talk_rules():
    rng = random.Random(1)
    assert P.small_talk("hola", rng).event == "greet"
    assert P.small_talk("Quiubo parce", rng).event == "greet"
    assert P.small_talk("muchas gracias!", rng).event == "thanks"
    assert P.small_talk("chao", rng) and P.small_talk("cómo estás", rng)
    assert P.small_talk("hola, recomiéndame algo de terror para jugar esta noche con mis amigos") is None   # largo
    assert P.small_talk("qué opinas de los roguelike") is None
    for line in P.GREETINGS + P.THANKS + P.BYES + P.HOWRU:
        assert line.count(".") + line.count("!") + line.count("?") <= 4 and len(line) < 160     # frases cortas


def test_advice_is_computed_by_code():
    g = lambda **k: GameInfo("X", **k)  # noqa: E731
    assert "mínimo histórico" in P.advice_line(g(sale_usd=5.0, historic_low_usd=5.0))
    assert "cerquita" in P.advice_line(g(sale_usd=6.0, historic_low_usd=5.0))
    assert "esperaría otra" in P.advice_line(g(sale_usd=7.5, historic_low_usd=5.0))
    assert "esperaría" in P.advice_line(g(sale_usd=20, historic_low_usd=5.0))
    assert "gratis" in P.advice_line(g(is_free=True))
    assert "No tengo su mínimo" in P.advice_line(g(sale_usd=5))                 # honesto: sin dato, lo dice
    assert "No tengo el precio" in P.advice_line(g())
    assert P.is_low_price(g(sale_usd=5.0, historic_low_usd=5.0)) and not P.is_low_price(g(sale_usd=9, historic_low_usd=5))


def test_minutes_and_wants_advice():
    assert P.minutes_available("tengo 30 minutos") == 30 and P.minutes_available("tengo 100.000 pesos") is None
    assert P.wants_advice("¿vale la pena Hades?") and not P.wants_advice("cuánto cuesta")
    assert "30" in P.time_line(30) and "tiempo de sobra" in P.time_line(120)


def test_reactions_only_key_moments_with_cooldown():
    t = [0.0]
    r = P.Reactions(cooldown=600, clock=lambda: t[0])
    assert r.should(1, "low_price") and not r.should(1, "greet")             # enfriamiento: no en cada mensaje
    assert not r.should(1, "evento_raro") and r.should(2, "greet")
    assert r.should(1, "achievement")                                          # logros siempre
    t[0] = 700
    assert r.should(1, "free")


def pipe(llm, persona=True, catalog=None):
    p = GamePipeline(make_service(catalog=catalog), Orchestrator(llm, "SYS"))
    p.persona = persona
    return p


async def test_casual_chat_costs_no_tokens_and_flag_off_uses_model():
    llm = FakeLLM("respuesta del modelo")
    p = pipe(llm)
    r = await p.handle("u", "hola")
    assert r.kind == "chat" and r.event == "greet" and llm.calls == 0
    assert (await p.handle("u", "gracias")).event == "thanks" and llm.calls == 0
    r = await p.handle("u", "qué opinas de los roguelike")                    # charla real: si usa modelo
    assert llm.calls == 1 and "modelo" in r.text
    p2 = pipe(FakeLLM("modelo"), persona=False)
    assert "modelo" in (await p2.handle("u", "hola")).text                    # flag apagado: comportamiento anterior


async def test_worth_it_adds_code_advice_and_minutes_lead_without_llm():
    llm = FakeLLM()
    p = pipe(llm, catalog=[{"title": "Hades", "genres": ["accion"], "tags": ["corto"], "platforms": ["pc"]}])
    r = await p.handle("u", "¿vale la pena Hades?")
    assert r.kind == "games" and ("esperaría" in r.summary or "mínimo" in r.summary or "cerquita" in r.summary)
    assert llm.calls == 0
    r = await p.handle("u", "tengo 30 minutos")
    assert r.kind == "games" and "30 minutos" in r.intro and llm.calls == 0       # frase de NEXUS por reglas
    r = await p.handle("u", "cuánto cuesta Hades")
    assert "esperaría" not in r.summary and "compraría" not in r.summary           # sin pedirlo, no aconseja


async def test_typing_indicator_and_slow_notice_once():
    bot = FakeBot()

    async def slow():
        await asyncio.sleep(0.35)
        return "ok"
    out = await with_typing(bot, 1, slow(), slow_after=0.1, interval=0.1, slow_text="pensando")
    assert out == "ok"
    kinds = [c[0] for c in bot.calls]
    assert kinds.count("action") >= 2 and sum(1 for c in bot.calls if c[0] == "msg" and c[1] == "pensando") == 1
    bot2 = FakeBot()

    async def fast():
        return 1
    assert await with_typing(bot2, 1, fast()) == 1 and not [c for c in bot2.calls if c[0] == "msg"]


async def test_reaction_needs_asset_cooldown_and_no_reaction_on_risk(tmp_path):
    h, A = make_handlers(tmp_path)
    install_features(A, h)
    install_persona(NS(), h)
    bot = FakeBot()
    u, m = upd("hola", bot=bot)
    h.deliver_called = None
    await h.react(u, "greet")                                                  # sin archivo: no hace ruido
    assert not [c for c in bot.calls if c[0] in ("photo", "anim")]
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "happy.png").write_bytes(PNG)
    A["mascot"].dir = tmp_path / "m"
    A["mascot"].enabled = True
    A["mascot"].scan()
    await h.react(u, "greet")
    assert [c[0] for c in bot.calls].count("photo") == 1
    await h.react(u, "thanks")                                                 # enfriamiento
    assert [c[0] for c in bot.calls].count("photo") == 1
    A["safety"].guard.mark(7)
    A["reactions"].forget(7)
    await h.react(u, "greet")
    assert [c[0] for c in bot.calls].count("photo") == 1                       # con riesgo: nunca


def test_reaction_event_mapping():
    from app.bot.handlers import BotHandlers
    from app.games.pipeline import Reply
    low = GameInfo("X", sale_usd=5, historic_low_usd=5)
    assert BotHandlers.reaction_event(Reply("games", "t", games=[low])) == "low_price"
    assert BotHandlers.reaction_event(Reply("free", "x Epic Games (esta semana) y")) == "free"
    assert BotHandlers.reaction_event(Reply("info", "No encontré «zzz»")) == "not_found"
    assert BotHandlers.reaction_event(Reply("chat", "x", event="greet")) == "greet"
    assert BotHandlers.reaction_event(Reply("chat", "x")) == ""


async def test_tip_view_with_data_and_fallback(tmp_path):
    h, A = make_handlers(tmp_path)
    install_persona(NS(), h)
    deals = [{"title": "Hades", "salePrice": "6.24", "normalPrice": "24.99", "savings": "75.0", "dealID": "D",
              "steamAppID": "1145360", "gameID": "196149", "steamRatingPercent": "98"}]

    def handler(req):
        if "cheapshark.com/api/1.0/deals" in str(req.url):
            return httpx.Response(200, json=deals)
        return base_handler(req)
    A["svc"].http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = NS(user_id=7, chat_id=1, arg="", app=A)
    v = await A["panel"].build("tip", ctx)
    assert "Consejo de NEXUS" in v.text and "Hades" in v.text and "CheapShark" in v.text and v.mascot in ("happy", "excited")

    def down(req):
        raise httpx.ConnectError("x")
    A["svc"].http._client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    A["svc"].http._cache.clear()
    A["svc"].http.retries = 0
    v = await A["panel"].build("tip", ctx)
    assert "consejo general" in v.text and "$" not in v.text                    # sin datos: consejo general, sin precios


async def test_persona_flag_off_everywhere(tmp_path):
    s = settings(tmp_path, mascot_voice_enabled=False)
    A = build_services(s)
    assert "PERSONALIDAD" not in A["orch"].system_prompt
    s2 = settings(tmp_path, mascot_voice_enabled=True)
    assert "NEXUS, un robot gamer parcero" in build_services(s2)["orch"].system_prompt
    h, A = make_handlers(tmp_path, mascot_voice_enabled=False)
    install_persona(NS(), h)
    assert A["pipe"].persona is False
    v = await A["panel"].build("tip", NS(user_id=7, chat_id=1, arg="", app=A))
    assert "apagada" in v.text
