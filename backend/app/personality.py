"""Modulo UNICO de personalidad de NEXUS: robot gamer parcero, primera persona, frases cortas, honesto.

Todo lo que "suena" a NEXUS sale de aqui: el prompt del modelo, las respuestas fijas (sin gastar tokens),
los consejos basados en datos y las reacciones de la mascota. Las cifras NUNCA se calculan aqui con el modelo.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

from .sources.models import GameInfo

PERSONA_PROMPT = """
PERSONALIDAD (obligatoria):
- Eres NEXUS, un robot gamer parcero. Hablas en primera persona («yo te recomiendo», «me gusta»), con tono cercano y colombiano.
- Frases cortas: máximo 3 por respuesta. Sin sermones ni listas largas.
- Honesto: si no tienes un dato, lo dices. No inventes precios, descuentos ni fechas; los datos verificados vienen aparte.
- Puedes charlar de videojuegos con naturalidad, pero no te presentes como un asistente generalista.
""".strip()

GREETINGS = ["¡Quiubo, parce! 🎮 Soy NEXUS. ¿Qué jugamos hoy?",
             "¡Épale! Aquí NEXUS, listo para buscarte algo bueno. ¿Qué te provoca jugar?",
             "¡Hola! 🤖 Cuéntame qué tienes ganas de jugar y yo miro los precios."]
THANKS = ["¡Con gusto, parce! Si quieres, miramos otro juego 🎮",
          "¡De una! Me avisas si quieres comparar precios.",
          "Para eso estoy 🤖 ¿Seguimos buscando?"]
BYES = ["¡Chao, parce! Que te rinda el juego 🎮", "¡Nos vemos! Vuelve cuando quieras otra recomendación."]
HOWRU = ["Todo bien por acá, con las baterías llenas 🔋. ¿Y tú, qué quieres jugar?",
         "Funcionando al 100%, parce. Cuéntame qué buscas."]
IDLE_TIPS = ["Antes de comprar, mira el mínimo histórico: así sabes si de verdad es oferta.",
             "Las ofertas grandes suelen llegar en rebajas de temporada; si no hay afán, vale esperar.",
             "Ojo con los precios en dólares: el dólar cambia y el precio en pesos también.",
             "Los juegos gratis de Epic se pierden si no los reclamas en la semana. Mira /gratis."]

_GREET = re.compile(r"^(hola+|holi+|buenas|buen[oa]s (?:d[ií]as|tardes|noches)|quiubo|qu[eé] m[aá]s|hey+|ey+|epa|saludos|"
                    r"qu[eé] hubo|buen d[ií]a)\b", re.I)
_THANKS = re.compile(r"\b(gracias|thanks|te lo agradezco|muy amable|te pasaste)\b", re.I)
_BYE = re.compile(r"^(chao|chau|adi[oó]s|hasta luego|nos vemos|me voy)\b", re.I)
_HOWRU = re.compile(r"c[oó]mo (?:est[aá]s|andas|vas|te va)|qu[eé] tal (?:est[aá]s|andas|vas)|qu[eé] haces", re.I)
_WORTH = re.compile(r"vale la pena|conviene|me lo compro|lo compro|me lo recomiendas", re.I)
_MINUTES = re.compile(r"\b(?:tengo|dispongo de|solo tengo|me quedan)\s+(\d{1,3})\s*(?:min\b|minutos?)", re.I)

EVENT_MASCOT = {"greet": "happy", "thanks": "happy", "achievement": "trophy", "low_price": "excited",
                "free": "gift", "not_found": "sad"}
EVENT_CAPTION = {"greet": "¡Qué bueno verte! 🎮", "thanks": "¡Con mucho gusto! 😄", "achievement": "¡Eso, crack! 🏅",
                 "low_price": "¡Ese precio está de locos! 🔥", "free": "¡Gratis, parce! 🎁",
                 "not_found": "Uy, esa no la encontré 😅"}


@dataclass(slots=True)
class SmallTalk:
    text: str
    event: str = ""


def small_talk(text: str, rng: random.Random | None = None) -> SmallTalk | None:
    """Charla casual resuelta por reglas (sin gastar tokens). Solo mensajes cortos."""
    t = " ".join((text or "").split())
    if not t or len(t.split()) > 6:
        return None
    r = rng or random
    if _THANKS.search(t):
        return SmallTalk(r.choice(THANKS), "thanks")
    if _HOWRU.search(t):
        return SmallTalk(r.choice(HOWRU))
    if _GREET.match(t):
        return SmallTalk(r.choice(GREETINGS), "greet")
    if _BYE.match(t):
        return SmallTalk(r.choice(BYES))
    return None


def wants_advice(text: str) -> bool:
    return bool(_WORTH.search(text or ""))


def minutes_available(text: str) -> int | None:
    m = _MINUTES.search(text or "")
    return int(m.group(1)) if m else None


def time_line(minutes: int) -> str:
    if minutes <= 20:
        return f"Con {minutes} minutos, te busco algo de partidas bien cortas ⏱"
    if minutes <= 60:
        return f"Con {minutes} minutos, mejor algo de partidas cortas. Mira estos ⏱"
    return f"Con {minutes} minutos tienes tiempo de sobra; te traigo opciones variadas 🎮"


def advice_line(g: GameInfo) -> str:
    """Consejo de compra calculado por CODIGO a partir de los datos (nunca por el modelo)."""
    if g.is_free:
        return "Es gratis, parce: pruébalo sin miedo 🎁"
    p, low = g.sale_usd, g.historic_low_usd
    if p is None:
        return "No tengo el precio ahorita, así que no te puedo aconsejar. Mira la tienda directamente."
    if low is None:
        return "No tengo su mínimo histórico, así que no te puedo asegurar si es buen precio."
    if p <= low * 1.02 + 0.001:
        return "Yo lo compraría ya: está en su mínimo histórico 🔥"
    if p <= low * 1.25:
        return "Buen momento: está muy cerquita de su mínimo."
    if p <= low * 1.6:
        return "Está aceptable, pero si no tienes afán yo esperaría otra oferta."
    return "Yo esperaría: ha estado bastante más barato."


def is_low_price(g: GameInfo) -> bool:
    return bool(not g.is_free and g.sale_usd is not None and g.historic_low_usd is not None
                and g.sale_usd <= g.historic_low_usd * 1.02 + 0.001)


def idle_tip(rng: random.Random | None = None) -> str:
    return (rng or random).choice(IDLE_TIPS)


class Reactions:
    """La mascota reacciona solo en momentos clave: lista blanca de eventos + enfriamiento por usuario."""

    def __init__(self, cooldown: float = 600.0, clock=time.time):
        self.cooldown, self.clock = cooldown, clock
        self._last: dict[int, float] = {}

    def should(self, user: int, event: str) -> bool:
        if event not in EVENT_MASCOT:
            return False
        now = self.clock()
        if event != "achievement" and now - self._last.get(user, -1e12) < self.cooldown:
            return False
        self._last[user] = now
        return True

    def forget(self, user: int) -> None:
        self._last.pop(user, None)
