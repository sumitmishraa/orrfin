"""Application settings, read from environment variables (BUILD_PLAN §3, §9).

Values come from the process environment first, then from the repo-root `.env`
file for local development. Real secrets never live in the repo: only
`.env.example` is committed, and on AWS the values come from Secrets Manager.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Orrfin Control Gate"
    app_env: str = "local"

    # SQLAlchemy URL using the pg8000 driver (see docs/adr/0001), e.g.
    # postgresql+pg8000://user:password@localhost:5432/orrfin
    database_url: str = "postgresql+pg8000://orrfin@localhost:5432/orrfin"

    # The Next.js dev server is the only browser origin allowed to call the API.
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
