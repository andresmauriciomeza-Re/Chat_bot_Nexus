import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.memory import ConversationMemory
from app.core.orchestrator import MSG_RATE, Orchestrator
from app.llm.base import LLMRateLimitError, LLMResult, LLMTimeoutError, LLMUnavailableError
from app.llm.groq_provider import GroqProvider
from app.logging_setup import mask, register_secret
from app.telegram_utils import esc, split_text


def mk(**kw):
    return Settings(_env_file=None, **kw)


def _env(monkeypatch, tok="123456:" + "a" * 30, key="k" * 10, model="m"):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", tok)
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv("GROQ_MODEL", model)


def test_settings_load(monkeypatch):
    _env(monkeypatch)
    s = mk()
    assert s.groq_model == "m" and "aaaa" not in repr(s)
    assert len(s.system_prompt()) > 20


def test_settings_fail_without_secrets(monkeypatch):
    for v in ("TELEGRAM_BOT_TOKEN", "GROQ_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(ValidationError):
        mk()


def test_empty_secret_rejected(monkeypatch):
    _env(monkeypatch, tok="  ")
    with pytest.raises(ValidationError):
        mk()


# ---- proveedor (pasa por httpx real con transporte simulado) ----
def provider(handler):
    return GroqProvider("k" * 12, "mod", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_provider_success_headers_ascii():
    seen = {}

    def h(req: httpx.Request):
        seen["url"] = str(req.url)
        for k, v in req.headers.items():
            v.encode("ascii")
        return httpx.Response(200, json={"choices": [{"message": {"content": " hola "}}], "usage": {"total_tokens": 42}})

    r = await provider(h).complete([{"role": "user", "content": "x"}])
    assert r.text == "hola" and r.tokens == 42 and seen["url"].endswith("/chat/completions")


@pytest.mark.parametrize("status,exc", [(429, LLMRateLimitError), (500, LLMUnavailableError), (401, LLMUnavailableError)])
async def test_provider_errors(status, exc):
    with pytest.raises(exc):
        await provider(lambda r: httpx.Response(status, json={"error": {"message": "x"}})).complete([{"role": "user", "content": "x"}])


async def test_provider_timeout_and_empty():
    def boom(req):
        raise httpx.ReadTimeout("t")
    with pytest.raises(LLMTimeoutError):
        await provider(boom).complete([])
    with pytest.raises(LLMUnavailableError):
        await provider(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})).complete([])
    with pytest.raises(LLMUnavailableError):
        GroqProvider("k", "")


# ---- memoria y orquestador ----
class Fake:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, max_tokens=350, user=None):
        self.calls.append(messages)
        return LLMResult("ok", 5)


class Boom:
    async def complete(self, messages, max_tokens=350, user=None):
        raise LLMRateLimitError()


def test_memory():
    m = ConversationMemory(max_stored=3)
    for i in range(5):
        m.add("a", "user", str(i))
    assert [x["content"] for x in m.get("a", 2)] == ["3", "4"]
    m.clear("a")
    assert m.get("a", 5) == []


async def test_orchestrator_context_isolation_reset():
    f = Fake()
    o = Orchestrator(f, "SYS")
    await o.handle("u1", "hola")
    await o.handle("u1", "otra")
    await o.handle("u2", "x")
    assert f.calls[1][0]["content"] == "SYS" and len(f.calls[1]) == 4 and len(f.calls[2]) == 2
    o.reset("u1")
    await o.handle("u1", "y")
    assert len(f.calls[3]) == 2


async def test_orchestrator_errors():
    o = Orchestrator(Boom(), "S")
    assert await o.handle("u", "hola") == MSG_RATE and o.memory.get("u", 9) == []
    assert "Escríbeme" in await o.handle("u", "  ")


def test_split_and_escape():
    t = ("palabra " * 1500).strip()
    parts = split_text(t)
    assert all(len(p) <= 4096 for p in parts) and " ".join(parts).split() == t.split()
    assert all(len(p) <= 10 for p in split_text("x" * 35, 10))
    assert esc("<b>&") == "&lt;b&gt;&amp;"


def test_mask():
    register_secret("supersecreto123")
    out = mask("x supersecreto123 y 123456789:" + "A" * 35 + " gsk_" + "b" * 20 + " /bot123:abc/getMe")
    assert "supersecreto" not in out and "AAAA" not in out and "gsk_b" not in out and "123:abc" not in out
