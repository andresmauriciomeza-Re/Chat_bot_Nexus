"""Configuracion central (pydantic-settings). Solo lee variables de entorno / backend/.env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    telegram_bot_token: SecretStr
    groq_api_key: SecretStr
    groq_model: str
    llm_provider: str = "groq"
    log_level: str = "INFO"

    # --- Fase 1: videojuegos ---
    games_enabled: bool = True
    cheapshark_enabled: bool = True
    steam_enabled: bool = True
    epic_enabled: bool = True
    trm_enabled: bool = True
    budget_sanity_max_cop: float = 1_000_000
    budget_sanity_max_usd: float = 300
    groq_budget_enabled: bool = True
    groq_daily_token_budget: int = 160_000
    groq_user_daily_tokens: int = 20_000
    data_dir: str = "data"

    # historial
    history_limit: int = 12
    llm_max_tokens: int = 350
    llm_timeout_s: float = 25.0

    @field_validator("telegram_bot_token", "groq_api_key")
    @classmethod
    def _not_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().strip():
            raise ValueError("el secreto no puede estar vacio")
        return v

    @field_validator("groq_model")
    @classmethod
    def _model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("GROQ_MODEL vacio")
        return v.strip()

    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    def system_prompt(self) -> str:
        return (BACKEND_DIR / "prompts" / "system.txt").read_text(encoding="utf-8").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
