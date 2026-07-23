"""Runtime configuration loaded from the repo-root .env (never from code).

Sandbox-only guard: this demo refuses to start against anything that is not
the Monnify sandbox. There is no override flag on purpose.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] is the repo root (chat-charge-trace/).
REPO_ROOT = Path(__file__).resolve().parents[2]


def _normalize_to_asyncpg(url: str) -> str:
    """Rewrite any postgres URL to the asyncpg async driver.

    ADK's DatabaseSessionService and our own order store both build async
    SQLAlchemy engines, so they need an async-driver URL. Bare
    (postgresql://), explicit sync driver (postgresql+psycopg2://),
    already-async (idempotent), and the short postgres:// form are all
    normalized. Non-postgres URLs (e.g. sqlite in tests) pass through.
    """
    postgres_prefixes = ("postgresql://", "postgresql+", "postgres://", "postgres+")
    if url.startswith(postgres_prefixes) and "://" in url:
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    monnify_api_key: str = ""
    monnify_secret_key: str = ""
    monnify_contract_code: str = ""
    monnify_base_url: str = "https://sandbox.monnify.com"

    google_api_key: str = ""
    google_model_name: str = "gemini-flash-latest"

    database_url: str = "postgresql+asyncpg://oja:oja@localhost:5433/oja"

    @property
    def async_database_url(self) -> str:
        """Async-driver URL for both the order store and ADK sessions."""
        return _normalize_to_asyncpg(self.database_url)

    @property
    def is_sandbox(self) -> bool:
        return "sandbox" in self.monnify_base_url

    def assert_sandbox(self) -> None:
        if not self.is_sandbox:
            raise RuntimeError(
                "Refusing a non-sandbox Monnify base URL. This workshop demo only "
                "ever talks to https://sandbox.monnify.com."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_sandbox()  # refuse startup outside the sandbox
    return settings
