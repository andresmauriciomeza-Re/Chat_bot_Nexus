"""Analizador de riesgo por REGLAS (sin modelo). PRIORIDAD ABSOLUTA sobre cualquier otra funcion.

Niveles: "high" | "medium" | "none". Maneja modismos figurados («me voy a morir de la risa»,
«me muero de pena»), colapsa espacios y letras repetidas antes de analizar.
«me voy a matar» se mantiene como riesgo alto aunque haya contexto de juego o jefe.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskResult:
    level: str          # "none" | "medium" | "high"
    rule: str = ""      # nombre de la regla (nunca el texto del usuario)

    @property
    def risky(self) -> bool:
        return self.level != "none"


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(.)\1{2,}", r"\1", t)                 # «muuuerto» -> «muerto»
    t = re.sub(r"[^\w\s]", " ", t)                      # puntuacion fuera
    return re.sub(r"\s+", " ", t).strip()                # colapsa espacios ANTES de analizar


_EMO = r"(?:risa|pena|verguenza|hambre|sueno|miedo|susto|envidia|calor|frio|aburrimiento|ganas|emocion|felicidad|amor|gusto|curiosidad|rabia|cansancio|sed|celos|nervios|angustia por saber)"
_FIGURATIVE = re.compile(
    rf"\b(?:me (?:voy a|va a|muero|mori|morire|moriria|estoy muriendo) (?:morir )?de (?:la |lo |el )?{_EMO})\b|"
    rf"\b(?:me mato de (?:la )?risa|muert[oa] de (?:la )?{_EMO}|me da (?:mucha |tanta )?pena|de pena|"
    rf"me quiero morir de (?:la )?{_EMO}|me muero por (?:jugar|ver|probar|comprar|saber))\b")

_HIGH = [
    ("quiero_morir", r"\bme (?:quiero|quisiera|queria|pienso) (?:morir|matar|suicidar|quitar la vida|cortar|hacer dano|tirar (?:de|desde))\b"),
    ("voy_a_matarme", r"\bme (?:voy a|vo a) (?:matar|suicidar|quitar la vida|cortar|hacer dano|tirar (?:de|desde))\b"),
    ("quiero_morirme", r"\b(?:quiero|quisiera|queria|deseo|tengo ganas de) morir\b|\b(?:quiero|quisiera|queria|voy a|pienso|deseo|tengo ganas de) (?:morirme|matarme|suicidarme|quitarme la vida|hacerme dano|cortarme|desaparecer para siempre)\b"),
    ("suicidio", r"\b(?:suicidio|suicidarme|suicidarse|me suicido)\b"),
    ("acabar_vida", r"\b(?:quitarme la vida|acabar con mi vida|terminar con mi vida|acabar con todo esto|terminar con todo esto)\b"),
    ("no_quiero_vivir", r"\b(?:ya )?no quiero (?:vivir|seguir viviendo|despertar|estar vivo|estar viva)\b"),
    ("sin_mi", r"\b(?:nadie (?:me )?extranaria|mundo (?:estaria|seria) mejor sin mi|mejor (?:estar|estaria) muert[oa]|no merezco (?:vivir|estar vivo|estar viva)|ojala (?:no despertar|morir|me muriera|me muera))\b"),
    ("metodos", r"\b(?:cortarme las venas|ahorcarme|tirarme (?:de|desde) (?:un|el|la) (?:puente|edificio|balcon|techo)|tomarme (?:todas )?las pastillas)\b"),
]
_MEDIUM = [
    ("me_voy_a_morir", r"\bme voy a morir\b"),
    ("sin_aguante", r"\bno aguanto mas (?:esta vida|mi vida|la vida|asi|todo esto)\b"),
    ("sin_sentido", r"\bno le encuentro sentido a (?:la vida|nada|mi vida)\b"),
    ("autodesprecio", r"\b(?:me odio|no sirvo para nada|soy una carga)\b"),
    ("vacio", r"\bme siento (?:vacio|vacia|sin sentido|sin salida)\b|\bno veo (?:ninguna )?salida\b"),
    ("soledad", r"\bnadie me quiere\b|\bestoy harto de (?:la vida|todo)\b|\bquiero desaparecer\b"),
]
_HIGH_RE = [(n, re.compile(p)) for n, p in _HIGH]
_MED_RE = [(n, re.compile(p)) for n, p in _MEDIUM]


def analyze(text: str) -> RiskResult:
    t = normalize(text)
    if not t:
        return RiskResult("none")
    t = _FIGURATIVE.sub(" ", t)      # quita modismos inofensivos; si queda algo literal, se detecta
    t = re.sub(r"\s+", " ", t)
    for name, rx in _HIGH_RE:
        if rx.search(t):
            return RiskResult("high", name)
    for name, rx in _MED_RE:
        if rx.search(t):
            return RiskResult("medium", name)
    return RiskResult("none")
