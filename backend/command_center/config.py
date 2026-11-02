"""Environment-based configuration. Nothing secret has a default."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected OWNER_PASSWORD must never be echoed into logs.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = Field(
        description="SQLAlchemy async URL, e.g. postgresql+asyncpg://user:pass@localhost:5432/command_center"
    )
    owner_password: SecretStr = Field(description="Dashboard owner password, at least 12 characters")
    owner_display_name: str = "Owner"

    # Comma-separated list of origins allowed for browser requests and WebSockets.
    # Only the app's own origin by default. The dashboard dev server (:3000) must be added explicitly.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    session_ttl_hours: int = 12
    cookie_secure: bool = False  # set true when served over HTTPS

    login_max_failures: int = 5
    login_window_seconds: int = 300

    ws_heartbeat_seconds: float = 15.0
    max_body_bytes: int = 128 * 1024
    enable_api_docs: bool = False
    web_dist: Path = Path(__file__).resolve().parents[2] / "apps" / "web" / "out"
    log_level: str = "INFO"

    @field_validator("owner_password")
    @classmethod
    def _password_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 12:
            raise ValueError("OWNER_PASSWORD must be at least 12 characters")
        return value

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @property
    def origins(self) -> set[str]:
        return {o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()}

    @property
    def allowed_hosts(self) -> list[str]:
        """Host header allowlist (DNS-rebinding guard): hosts of the allowed origins plus loopback."""
        hosts = {"localhost", "127.0.0.1"}
        for origin in self.origins:
            host = origin.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
            if host:
                hosts.add(host)
        return sorted(hosts)

    @property
    def asyncpg_dsn(self) -> str:
        """Plain DSN for the raw asyncpg LISTEN connection."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
