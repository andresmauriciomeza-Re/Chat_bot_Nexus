"""Filtros en lenguaje natural por reglas de codigo (genero, gratis, oferta, plataforma, etiquetas)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .budget import Amount, parse_amount

GENRES = {
    "accion": r"acci[oó]n|action",
    "aventura": r"aventura",
    "rpg": r"\brpg\b|\brol\b|juegos? de rol",
    "estrategia": r"estrateg",
    "indie": r"indie|independiente",
    "simulacion": r"simulaci|simulador",
    "carreras": r"carrera|conducci|manejar|autos|carros",
    "deportes": r"deporte|f[uú]tbol|baloncesto|\bnba\b",
    "puzzle": r"puzzle|puzle|rompecabezas|acertijo",
    "terror": r"terror|miedo|horror|susto",
    "plataformas": r"plataformas|platformer",
    "shooter": r"shooter|disparos|\bfps\b|tiros",
    "roguelike": r"roguelike|rogue-?lite",
    "mundo_abierto": r"mundo abierto|open world",
    "lucha": r"\blucha\b|peleas|fighting",
    "supervivencia": r"supervivencia|survival",
}
GENRE_LABEL = {"accion": "acción", "aventura": "aventura", "rpg": "RPG", "estrategia": "estrategia",
               "indie": "indie", "simulacion": "simulación", "carreras": "carreras", "deportes": "deportes",
               "puzzle": "puzzle", "terror": "terror", "plataformas": "plataformas", "shooter": "shooter",
               "roguelike": "roguelike", "mundo_abierto": "mundo abierto", "lucha": "lucha",
               "supervivencia": "supervivencia"}
TAGS = {
    "coop": r"\bcoop|cooperativ|con (?:mis )?amigos|con mi pareja|en pareja",
    "multijugador": r"multijugador|online|en l[ií]nea",
    "relajado": r"relaj|chill|tranquil|sin estr[eé]s|cozy|acogedor|descansar",
    "corto": r"\b(?:15|20|30|40|45) ?min|partidas? cortas?|\bcorto|r[aá]pid|poco tiempo",
    "historia": r"historia|narrativ|story",
    "desafiante": r"dif[ií]cil|reto|desafi|hardcore",
    "familiar": r"ni[ñn]os|familia|familiar",
    "competitivo": r"competitiv|ranked|e-?sports",
}
PLATFORMS = {
    "pc": r"\bpc\b|computador|steam|windows",
    "ps": r"playstation|\bps ?[345]\b|\bps\b",
    "xbox": r"xbox",
    "switch": r"switch|nintendo",
}
PLATFORM_LABEL = {"pc": "PC", "ps": "PlayStation", "xbox": "Xbox", "switch": "Switch"}
_FREE = re.compile(r"\bgratis\b|gratuit|\bfree\b|f2p|free to play|regalad", re.I)
_SALE = re.compile(r"oferta|descuento|rebaja|promo|\bbarat|en sale", re.I)


@dataclass(slots=True)
class Filters:
    genres: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    platforms: set[str] = field(default_factory=set)
    free: bool = False
    on_sale: bool = False
    amount: Amount | None = None
    max_usd: float | None = None

    @property
    def empty(self) -> bool:
        return not (self.genres or self.tags or self.platforms or self.free or self.on_sale or self.amount)

    def describe(self) -> str:
        bits = [GENRE_LABEL[g] for g in sorted(self.genres)] + sorted(self.tags) \
            + [PLATFORM_LABEL[p] for p in sorted(self.platforms)]
        if self.free:
            bits.append("gratis")
        if self.on_sale:
            bits.append("en oferta")
        return ", ".join(bits)


def parse_filters(text: str, max_cop: float = 1_000_000, max_usd: float = 300) -> Filters:
    t = text.lower()
    f = Filters()
    f.genres = {g for g, p in GENRES.items() if re.search(p, t)}
    f.tags = {g for g, p in TAGS.items() if re.search(p, t)}
    f.platforms = {g for g, p in PLATFORMS.items() if re.search(p, t)}
    f.free = bool(_FREE.search(t))
    f.on_sale = bool(_SALE.search(t))
    f.amount = parse_amount(text, max_cop, max_usd)
    return f
