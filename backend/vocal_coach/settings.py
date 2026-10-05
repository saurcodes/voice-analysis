"""Process-level settings from environment / .env (not from config.yaml)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BYTES_PER_MB = 1024 * 1024
JWKS_PATH = "/protocol/openid-connect/certs"  # Keycloak OIDC JWKS endpoint, relative to the realm issuer


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach"
    keycloak_issuer: str = "http://localhost:8080/realms/vocal-coach"
    keycloak_audience: str = "vocal-coach-web"
    # In compose the browser sees Keycloak at localhost:8080 (the issuer) but the backend container
    # must fetch JWKS via the compose network; this override points only the fetch elsewhere.
    keycloak_jwks_url_override: str | None = None
    frontend_origin: str = "http://localhost:5173"
    data_dir: Path = Path("data")
    job_workers: int = 1
    max_upload_mb: int = 500
    require_ffmpeg: bool = True
    openai_compat_api_key: str | None = None
    anthropic_api_key: str | None = None
    # In compose the backend container cannot reach a host-run Ollama at localhost; this override
    # points the LLM provider's base_url elsewhere (e.g. http://host.docker.internal:11434/v1).
    llm_base_url_override: str | None = None
    secret_key: str = "dev-secret-change-me"
    drive_token_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/drive/callback"

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url_override or (self.keycloak_issuer.rstrip("/") + JWKS_PATH)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * BYTES_PER_MB

    @property
    def drive_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.drive_token_key)


def get_settings() -> Settings:
    return Settings()
