"""Compuerta de seguridad emocional: se evalua ANTES que cualquier otra funcion (teclado, voz, XP, inline...)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..analysis.analyzer import analyze
from .orchestrator import Orchestrator
from .risk_guard import RiskGuard

SUPPORT_HIGH = (
    "Siento mucho que estés pasando por esto 💜. Lo que sientes importa y no tienes que cargarlo solo.\n\n"
    "Si estás en peligro o piensas hacerte daño, por favor llama ya al <b>123</b> (emergencias) o a la "
    "<b>Línea 106</b> (apoyo emocional, es gratis). Si puedes, busca a alguien de confianza que esté cerca y cuéntale cómo te sientes.\n\n"
    "Aquí estoy contigo, sin afán. ¿Quieres contarme qué pasó?")
SUPPORT_MEDIUM = (
    "Gracias por contármelo 💜. Suena a que lo estás pasando duro.\n\n"
    "Si en algún momento sientes que no puedes más, llama al <b>123</b> o a la <b>Línea 106</b> (apoyo emocional gratuito). "
    "Hablar con alguien de confianza también ayuda mucho.\n\nAquí sigo, ¿quieres contarme más?")
GUARD_SOFT = ("Aquí sigo contigo 💜. Por ahora prefiero que hablemos tranquilos, sin menús ni juegos. "
              "Si lo necesitas, el <b>123</b> y la <b>Línea 106</b> están disponibles. "
              "Cuando te sientas mejor, escríbeme «ya estoy bien» y seguimos con los juegos.")
RELEASED = "Qué bueno leerte así 💜. Cuando quieras, seguimos con los juegos 🎮"
_RELEASE = re.compile(r"\b(ya estoy bien|estoy mejor|ya me siento mejor|ya pas[oó]|sigamos|seguimos|continuemos|quiero seguir)\b", re.I)
SUPPORT_FACT = ("El usuario pasó hace poco por un momento emocional difícil. Responde con calidez, MUY breve (máx 3 frases), "
                "sin recomendar juegos, sin precios, sin emojis de juego. Recuérdale que existe el 123 y la Línea 106 si lo necesita.")


@dataclass(slots=True)
class Verdict:
    kind: str          # "ok" | "risk" | "guard" | "released"
    text: str = ""

    @property
    def blocked(self) -> bool:
        return self.kind != "ok"


class Safety:
    def __init__(self, guard: RiskGuard, orch: Orchestrator | None = None, enabled: bool = True):
        self.guard, self.orch, self.enabled = guard, orch, enabled

    def active(self, user) -> bool:
        return self.enabled and self.guard.active(user)

    def check(self, user, text: str) -> Verdict:
        """Sincrono y sin red. No guarda ni registra el texto."""
        if not self.enabled:
            return Verdict("ok")
        r = analyze(text)
        if r.risky:
            self.guard.mark(user)
            return Verdict("risk", SUPPORT_HIGH if r.level == "high" else SUPPORT_MEDIUM)
        if self.guard.active(user):
            if _RELEASE.search(text or ""):
                self.guard.release(user)
                return Verdict("released", RELEASED)
            return Verdict("guard", GUARD_SOFT)
        return Verdict("ok")

    async def guard_reply(self, user, text: str) -> str:
        """Respuesta de apoyo (solo texto) durante la guardia: modelo si hay cupo; si no, mensaje fijo."""
        if self.orch:
            ans, _ = await self.orch.ask(str(user), text, facts=SUPPORT_FACT, store=False, max_tokens=140)
            if ans:
                from ..telegram_utils import esc
                return esc(ans)
        return GUARD_SOFT
