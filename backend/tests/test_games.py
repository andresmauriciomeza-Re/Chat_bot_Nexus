import json
import random

import httpx
import pytest

from app.core.orchestrator import MSG_QUOTA_GLOBAL, MSG_QUOTA_USER, Orchestrator
from app.games.budget import Amount, parse_amount
from app.games.filters import parse_filters
from app.games.pipeline import GamePipeline
from app.games.render import fmt_cop, render_free, render_game
from app.games.service import GameService, affordable, price_verdict
from app.llm.base import LLMRateLimitError, LLMResult
from app.llm.budget import BudgetedLLM, LLMBudgetError, TokenBudget
from app.sources.http import USER_AGENT, Http
from app.sources.models import GameInfo


# ---------------- presupuesto ----------------
@pytest.mark.parametrize("text,val,cur", [
    ("tengo 300 mil", 300_000, "COP"),
    ("$1.500.000", 1_500_000, "COP"),
    ("tengo 100.000 pesos", 100_000, "COP"),
    ("100.000 mil pesos", 100_000, "COP"),      # redundancia
    ("50 dólares", 50, "USD"),
    ("hasta 20 usd", 20, "USD"),
    ("1,5 millones", 1_500_000, "COP"),
    ("50 lucas", 50_000, "COP"),
    ("un presupuesto de $50 usd", 50, "USD"),
    ("tengo 150000", 150_000, "COP"),
    ("49.99 dolares", 49.99, "USD"),
])
def test_parse_amount(text, val, cur):
    a = parse_amount(text)
    assert a and a.value == pytest.approx(val) and a.currency == cur


@pytest.mark.parametrize("text", ["hola", "FIFA 23", "tengo 30 minutos", "quiero jugar algo", "juego de 2 jugadores"])
def test_parse_amount_none(text):
    assert parse_amount(text) is None


def test_sanity_threshold():
    assert parse_amount("tengo 2 millones").needs_confirm
    assert not parse_amount("tengo 1.000.000 pesos").needs_confirm
    assert parse_amount("500 dólares").needs_confirm
    assert not parse_amount("300 dolares").needs_confirm
    assert parse_amount("5 millones", max_cop=10_000_000).needs_confirm is False


def test_filters():
    f = parse_filters("algo gratis de terror para PC en oferta con amigos")
    assert f.free and f.on_sale and "terror" in f.genres and "pc" in f.platforms and "coop" in f.tags
    assert parse_filters("quiero algo relajado para jugar 30 minutos").tags == {"relajado", "corto"}
    assert parse_filters("hola").empty


# ---------------- veredicto ----------------
def g(**kw):
    return GameInfo(title="X", **kw)


def test_verdict():
    assert "mínimo histórico" in price_verdict(g(sale_usd=5.0, historic_low_usd=5.0))
    assert "Buen precio" in price_verdict(g(sale_usd=6.0, historic_low_usd=5.0))
    assert "Aceptable" in price_verdict(g(sale_usd=7.5, historic_low_usd=5.0))
    assert "espera" in price_verdict(g(sale_usd=20, historic_low_usd=5.0))
    assert "gratis" in price_verdict(g(is_free=True, sale_usd=0.0))
    assert "No tengo su mínimo" in price_verdict(g(sale_usd=5))
    assert "Sin precio" in price_verdict(g())


def test_affordable_and_fmt():
    assert affordable(g(price_cop=50_000), Amount(60_000, "COP"), 4000)
    assert not affordable(g(price_cop=70_000), Amount(60_000, "COP"), 4000)
    assert affordable(g(sale_usd=10), Amount(20, "USD"), None)
    assert not affordable(g(sale_usd=10), Amount(60_000, "COP"), None)      # sin TRM no se inventa
    assert fmt_cop(1500000) == "$1.500.000"


# ---------------- fuentes con httpx REAL + transporte simulado ----------------
TRM_J = [{"valor": "4000.50", "vigenciadesde": "2026-11-23"}]
DEALS_J = {"info": {"title": "Hades", "steamAppID": "1145360"}, "cheapestPriceEver": {"price": "6.24", "date": 1},
           "deals": [{"storeID": "1", "dealID": "ABC%3D", "price": "12.49", "retailPrice": "24.99", "savings": "50.0"}]}
EPIC_J = {"data": {"Catalog": {"searchStore": {"elements": [
    {"title": "Juego Gratis", "keyImages": [{"type": "Thumbnail", "url": "https://i/x.jpg"}],
     "offerMappings": [{"pageSlug": "juego-gratis"}],
     "promotions": {"promotionalOffers": [{"promotionalOffers": [
         {"endDate": "2026-12-01T15:00:00.000Z", "discountSetting": {"discountPercentage": 0}}]}],
         "upcomingPromotionalOffers": []}},
    {"title": "Con Descuento", "promotions": {"promotionalOffers": [{"promotionalOffers": [
        {"discountSetting": {"discountPercentage": 50}}]}]}}]}}}}


def steam_details(appid, name, final_cents=5880000):
    return {str(appid): {"success": True, "data": {
        "name": name, "is_free": False, "header_image": "https://h/x.jpg", "short_description": "Desc x",
        "genres": [{"description": "Acción"}, {"description": "Indie"}],
        "categories": [{"description": "Un jugador"}], "platforms": {"windows": True, "mac": False, "linux": False},
        "price_overview": {"currency": "COP", "initial": final_cents * 2, "final": final_cents, "discount_percent": 50},
        "metacritic": {"score": 93}}}}


def handler(req: httpx.Request) -> httpx.Response:
    assert req.headers["user-agent"] == USER_AGENT          # cabeceras validas de verdad
    req.headers["user-agent"].encode("ascii")
    u = str(req.url)
    if "datos.gov.co" in u:
        return httpx.Response(200, json=TRM_J)
    if "cheapshark.com/api/1.0/stores" in u:
        return httpx.Response(200, json=[{"storeID": "1", "storeName": "Steam"}])
    if "cheapshark.com/api/1.0/games" in u:
        if req.url.params.get("id"):
            return httpx.Response(200, json=DEALS_J)
        t = req.url.params.get("title", "").lower()
        if "hades" in t:
            return httpx.Response(200, json=[{"gameID": "196149", "steamAppID": "1145360", "external": "Hades",
                                              "cheapest": "12.49", "thumb": "https://t/x.jpg"}])
        return httpx.Response(200, json=[])
    if "cheapshark.com/api/1.0/deals" in u:
        return httpx.Response(200, json=[{"title": "Regalo", "salePrice": "0.00", "normalPrice": "9.99",
                                          "savings": "100", "dealID": "Z", "steamAppID": "0"}])
    if "storesearch" in u:
        return httpx.Response(200, json={"items": []})
    if "appdetails" in u:
        return httpx.Response(200, json=steam_details(1145360, "Hades"))
    if "freeGamesPromotions" in u:
        return httpx.Response(200, json=EPIC_J)
    return httpx.Response(404)


def make_service(h=handler, catalog=None):
    http = Http(httpx.AsyncClient(transport=httpx.MockTransport(h), headers={"User-Agent": USER_AGENT}),
                retries=1, backoff=0)
    return GameService(http, catalog=catalog if catalog is not None else [], rng=random.Random(1))


async def test_get_game_hades_merge():
    s = make_service()
    gm = await s.get_game("Hades")
    assert gm.price_cop == 58800 and gm.sale_usd == 12.49 and gm.historic_low_usd == 6.24
    assert gm.genres == ["Acción", "Indie"] and gm.store_name == "Steam" and gm.discount_pct == 50
    trm = await s.cop_per_usd()
    assert trm == 4000.5
    txt = render_game(gm, trm)
    assert "Hades" in txt and "$58.800" in txt and "(Steam)" in txt and "-50%" in txt


async def test_free_today():
    s = make_service()
    epic, giv = await s.free_today()
    assert [e.title for e in epic] == ["Juego Gratis"] and epic[0].url.endswith("/juego-gratis")
    assert giv[0].title == "Regalo"
    out = render_free(epic, giv)
    assert "Juego Gratis" in out and "CheapShark" in out


async def test_degradation_all_sources_down():
    def down(req):
        raise httpx.ConnectError("sin red")
    s = make_service(down)
    assert await s.get_game("Hades") is None
    assert await s.cop_per_usd() is None
    epic, giv = await s.free_today()
    assert epic is None and giv == []
    assert "No pude consultar Epic" in render_free(epic, giv)


async def test_trm_fallback_after_retries():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if "datos.gov.co" in str(req.url):
            return httpx.Response(500)
        return httpx.Response(200, json={"rates": {"COP": 3900.0}})
    s = make_service(h)
    assert await s.cop_per_usd() == 3900.0
    assert calls["n"] == 3            # 2 intentos a datos.gov.co (reintento) + 1 al respaldo


async def test_cache_ttl_avoids_second_call():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(200, json=TRM_J)
    s = make_service(h)
    await s.cop_per_usd()
    await s.cop_per_usd()
    assert calls["n"] == 1


async def test_flag_disables_source():
    s = make_service()
    s.enabled["steam"] = False
    gm = await s.get_game("Hades")
    assert gm.price_cop is None and gm.sale_usd == 12.49


# ---------------- pipeline ----------------
class FakeLLM:
    def __init__(self, text="Mira estos 🎮"):
        self.text, self.calls = text, 0

    async def complete(self, messages, max_tokens=350, user=None):
        self.calls += 1
        return LLMResult(self.text, 30)


def pipeline(llm=None, catalog=None):
    s = make_service(catalog=catalog)
    orch = Orchestrator(llm or FakeLLM(), "SYS")
    return GamePipeline(s, orch), orch


CAT = [{"title": "Hades", "genres": ["accion", "roguelike"], "tags": ["corto"], "platforms": ["pc"]}]


async def test_price_intent_no_llm_and_html_escaped():
    llm = FakeLLM()
    p, _ = pipeline(llm)
    r = await p.handle("u", "cuánto cuesta Hades?")
    assert r.kind == "games" and r.games[0].title == "Hades" and "$58.800" in r.text and llm.calls == 0
    r = await p.handle("u", "cuánto cuesta <script>")
    assert "<script>" not in r.text


async def test_sheet_and_compare_and_free():
    p, _ = pipeline()
    assert (await p.handle("u", "ficha de Hades")).kind == "sheet"
    c = await p.handle("u", "Hades vs Hades")
    assert c.kind == "compare" and "Valen lo mismo" in c.text
    assert (await p.handle("u", "qué hay gratis hoy")).kind == "free"


async def test_recommend_budget_and_confirmation():
    p, _ = pipeline(catalog=CAT)
    r = await p.handle("u", "recomiéndame un juego de acción, tengo 100.000 pesos")
    assert r.kind == "games" and r.games[0].title == "Hades" and "Mira estos" in r.text
    r = await p.handle("u", "recomiéndame algo de acción, tengo 2 millones de pesos")
    assert r.kind == "confirm"
    r = await p.handle("u", "sí")
    assert r.kind == "games"
    r = await p.handle("u", "tengo 5 millones de pesos")
    assert r.kind == "confirm"
    assert (await p.handle("u", "no")).kind == "info"


async def test_recommend_too_cheap_says_nothing_found():
    p, _ = pipeline(catalog=CAT)
    r = await p.handle("u", "recomiéndame algo de acción, tengo 10.000 pesos")
    assert r.kind == "info" and "No encontré" in r.text


async def test_recommend_works_without_llm():
    class Down:
        async def complete(self, *a, **k):
            raise LLMRateLimitError()
    p, _ = pipeline(Down(), catalog=CAT)
    r = await p.handle("u", "recomiéndame un juego de acción")
    assert r.kind == "games" and "Hades" in r.text and "encontré" in r.text.lower()


async def test_chat_goes_to_llm_escaped():
    p, _ = pipeline(FakeLLM("hola <b>x"))
    r = await p.handle("u", "qué onda")
    assert r.kind == "chat" and "&lt;b&gt;" in r.text


# ---------------- presupuesto de tokens ----------------
class Clock:
    t = 1_700_000_000.0

    def __call__(self):
        return self.t


async def test_token_budget_global_user_cooldown_and_reset(tmp_path):
    clk = Clock()
    b = TokenBudget(True, daily_tokens=1000, per_user_tokens=400, path=tmp_path / "b.json", cooldown_s=30, clock=clk)
    llm = BudgetedLLM(FakeLLM(), b)
    msgs = [{"role": "user", "content": "hola"}]
    await llm.complete(msgs, max_tokens=50, user="a")
    b.record("a", 400)
    with pytest.raises(LLMBudgetError) as e:
        await llm.complete(msgs, max_tokens=50, user="a")
    assert e.value.reason == "user"
    b.record("b", 600)
    with pytest.raises(LLMBudgetError) as e:
        await llm.complete(msgs, max_tokens=50, user="c")
    assert e.value.reason == "global"
    assert json.loads((tmp_path / "b.json").read_text())["total"] >= 1000
    assert TokenBudget(True, 1000, 400, path=tmp_path / "b.json", clock=clk).total >= 1000   # persiste
    clk.t += 86400
    assert b.check("a", 10) is None                                   # nuevo dia
    b.rate_limited()
    assert b.check("a", 10) == "cooldown"
    clk.t += 31
    assert b.check("a", 10) is None
    assert TokenBudget(False, 1, 1).check("x", 99999) is None         # desactivado


async def test_orchestrator_fixed_messages_when_quota_out():
    class Out:
        def __init__(self, r):
            self.r = r

        async def complete(self, *a, **k):
            raise LLMBudgetError(self.r)
    assert await Orchestrator(Out("user"), "S").handle("u", "hola") == MSG_QUOTA_USER
    assert await Orchestrator(Out("global"), "S").handle("u", "hola") == MSG_QUOTA_GLOBAL


async def test_rate_limit_sets_cooldown():
    class RL:
        async def complete(self, *a, **k):
            raise LLMRateLimitError()
    b = TokenBudget(True)
    with pytest.raises(LLMRateLimitError):
        await BudgetedLLM(RL(), b).complete([{"role": "user", "content": "x"}], user="u")
    assert b.check("u") == "cooldown"
