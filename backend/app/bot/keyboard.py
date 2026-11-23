"""Teclado fijo de 6 botones (se atiende ANTES del orquestador, sin gastar cupo)."""
from __future__ import annotations

from telegram import ReplyKeyboardMarkup

LABELS = {
    "🏠 Menú": "menu",
    "🎮 Recomiéndame": "reco",
    "🆓 Gratis hoy": "free",
    "😊 Mi ánimo": "mood",
    "🏆 Mi perfil": "profile",
    "🧠 Trivia": "trivia",
}


def main_keyboard() -> ReplyKeyboardMarkup:
    keys = list(LABELS)
    rows = [keys[i:i + 2] for i in range(0, len(keys), 2)]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               input_field_placeholder="Escríbeme un juego o usa el teclado 🎮")


def label_to_view(text: str) -> str | None:
    return LABELS.get((text or "").strip())
