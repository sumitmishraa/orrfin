"""Application settings, read from environment variables (BUILD_PLAN §3, §9).

Values come from the process environment first, then from the repo-root `.env`
file for local development. Real secrets never live in the repo: only
`.env.example` is committed, and on AWS the values come from Secrets Manager.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
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

    # Restricted Postgres role the app switches to after connecting (docs/adr/0002).
    # Empty string disables the switch (never do that outside a one-off admin script).
    db_app_role: str = "orrfin_app"

    # The Next.js dev server is the only browser origin allowed to call the API.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Login session (§3, §9): server-side row, opaque token in an HttpOnly cookie.
    session_cookie_name: str = "orrfin_session"
    session_hours: int = 12
    # Browsers only send Secure cookies over HTTPS; local development is plain HTTP.
    session_cookie_secure: bool = False
    # Password guessing (§9): this many wrong passwords for one email locks it for this long.
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # Where the simulated ERPNext reads its JSON fixtures (Step 4); relative to the repo root.
    erp_fixtures_dir: str = "seed/erpnext"
    # Master key that encrypts ERP credentials saved on the Connectors page (ADR 0006). A Fernet key:
    # scripts/dev.ps1 creates one in .env on first run. Never committed; Secrets Manager on AWS.
    orrfin_secret_key: SecretStr | None = None
    # Where the browser is sent back after an ERP's OAuth sign-in (Zoho, Step 20).
    public_web_url: str = "http://localhost:3000"

    # --- AI (BUILD_PLAN §3 AI row, §7). One provider serves extraction and explanations.
    # "gemini" (Google Gemini API: the working provider until Bedrock access is granted, ADR 0005),
    # "bedrock" (the plan), "anthropic" (the plan's direct-API alternative) or "fake", which
    # returns the Step 6 answer keys for the evaluation PDFs: a clearly labelled stand-in
    # used in tests. It never pretends to be a model.
    ai_provider: str = "gemini"
    # From docs/spikes.md: from Mumbai, current models exist only as global inference profiles.
    bedrock_model_id: str = "global.anthropic.claude-sonnet-5-5"
    aws_region: str = "ap-south-1"
    # The laptop uses the AWS CLI "default" profile; on EC2 set AWS_PROFILE to empty so the
    # instance role is used instead (Step 14).
    aws_profile: str | None = "default"
    anthropic_model: str = "claude-sonnet-5-5"
    # Only for ai_provider = "anthropic"; lives in .env (never committed).
    anthropic_api_key: SecretStr | None = None
    # Only for ai_provider = "gemini"; key from aistudio.google.com, lives in .env (never committed).
    # A stable model ID (not a "-latest" alias), so eval results stay tied to one model.
    gemini_model: str = "gemini-3.8-flash"
    gemini_api_key: SecretStr | None = None

    # --- Uploaded files (BUILD_PLAN §9 upload limits). Local disk now; S3 at deploy (Step 14).
    file_store_dir: str = "storage"  # relative to the repo root; git-ignored
    max_upload_bytes: int = 10 * 1024 * 1024

    @model_validator(mode="after")
    def _refuse_unsafe_settings_outside_local(self) -> "Settings":
        """Fail closed: a deployed server must not start with laptop-only safety settings.

        The local defaults are convenient and unsafe on the internet (a cookie sent over plain
        HTTP, no key for ERP credentials, a localhost web address). A forgotten setting should
        stop the server with a clear message, not run quietly in a weak state.
        """
        if self.app_env == "local":
            return self
        problems = []
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true (the login cookie may only travel over HTTPS)")
        if self.orrfin_secret_key is None:
            problems.append("ORRFIN_SECRET_KEY must be set (it encrypts saved ERP credentials)")
        web_addresses = [*self.cors_origins, self.public_web_url]
        if any(not address.startswith("https://") for address in web_addresses):
            problems.append("CORS_ORIGINS and PUBLIC_WEB_URL must be https:// addresses of the deployed web app")
        if self.ai_provider == "fake":
            problems.append("AI_PROVIDER=fake returns answer keys and is for tests only")
        if problems:
            raise ValueError(f"Unsafe settings for APP_ENV={self.app_env}: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
