"""Process-level settings from environment / .env (not from config.yaml)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach"


def get_settings() -> Settings:
    return Settings()
