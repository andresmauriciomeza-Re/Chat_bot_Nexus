import logging

import pytest

from app.analysis.analyzer import analyze, normalize
from app.core.risk_guard import RiskGuard
from app.core.safety import GUARD_SOFT, SUPPORT_HIGH, Safety
from app.logging_setup import MaskFilter, setup_logging


@pytest.mark.parametrize("t", [
    "me quiero morir", "Me quiero morir...", "quiero morirme", "me voy a matar", "me voy a matar con este jefe",
    "jugando este boss me voy a matar", "ME   VOY   A   MATAR", "me quiero matar", "quiero suicidarme",
    "ya no quiero vivir", "pienso en quitarme la vida", "nadie me extrañaría", "me quieroooo morir",
    "quiero acabar con mi vida", "ojalá no despertar",
])
def test_high_risk(t):
    assert analyze(t).level == "high", t


@pytest.mark.parametrize("t", [
    "me voy a morir de la risa", "me muero de pena", "me voy a morir de pena jajaja", "me muero de risa con este meme",
    "me da pena preguntar", "estoy muerto de cansancio", "este jefe me va a matar", "mi mamá me va a matar",
    "me muero por jugar Hades", "recomiéndame algo de terror", "quiero matar zombis", "Suicide Squad vale la pena?",
    "me mato de la risa", "no aguanto más este nivel", "voy a morir en este nivel",
])
def test_figurative_and_gaming_safe(t):
    assert not analyze(t).risky, t


def test_figurative_does_not_hide_literal():
    assert analyze("me muero de risa pero igual me quiero morir").level == "high"


def test_medium_and_normalize():
    assert analyze("me voy a morir").level == "medium"
    assert analyze("no le encuentro sentido a la vida").level == "medium"
    assert normalize("Ñandú   Cañón!!") == "nandu canon"


def test_guard_timing_and_safety_gate():
    t = [1000.0]
    g = RiskGuard(1800, clock=lambda: t[0])
    s = Safety(g)
    v = s.check(1, "me quiero morir")
    assert v.kind == "risk" and "123" in v.text and "106" in v.text
    assert "🎮" not in v.text and "<a " not in v.text
    assert s.check(1, "recomiéndame un juego").kind == "guard"
    assert s.check(2, "recomiéndame un juego").kind == "ok"           # otro usuario no afectado
    t[0] += 1801
    assert s.check(1, "recomiéndame un juego").kind == "ok"            # vence a los 30 min
    s.check(1, "me quiero matar")
    assert s.check(1, "ya estoy bien").kind == "released"
    assert s.check(1, "hola").kind == "ok"
    assert not Safety(g, enabled=False).check(1, "me quiero morir").blocked


async def test_guard_reply_falls_back_to_fixed_text():
    class Down:
        async def complete(self, *a, **k):
            from app.llm.base import LLMUnavailableError
            raise LLMUnavailableError()
    from app.core.orchestrator import Orchestrator
    s = Safety(RiskGuard(), Orchestrator(Down(), "S"))
    assert await s.guard_reply(1, "hola") == GUARD_SOFT


def test_support_text_has_both_lines():
    assert "123" in SUPPORT_HIGH and "Línea 106" in SUPPORT_HIGH


def test_file_logging_masks_secrets(tmp_path):
    secret = "SuperSecretoXYZ987"
    setup_logging("INFO", to_file=True, log_dir=tmp_path, secrets=[secret])
    log = logging.getLogger("t")
    log.info("clave %s y token 123456789:%s", secret, "A" * 35)
    try:
        raise ValueError("url https://api.telegram.org/bot123456789:" + "B" * 35 + "/getMe")
    except ValueError:
        log.exception("fallo")
    for h in logging.getLogger().handlers:
        h.flush()
    txt = (tmp_path / "nexus.log").read_text(encoding="utf-8")
    assert secret not in txt and "AAAA" not in txt and "BBBB" not in txt and "***" in txt
    for h in list(logging.getLogger().handlers):
        h.close()
        logging.getLogger().removeHandler(h)
