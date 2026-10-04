"""Shared test setup: a separate `<db>_test` database, migrated to head, emptied per run.

Database tests use their own database so they never touch development data. On a
laptop without Postgres they are skipped; in CI (the CI variable is set) a missing
database is a failure. Each test builds its own org with unique emails, so tests
don't depend on each other's rows.
"""

import os
import tempfile
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError

from app.config import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "correct-horse-test"

# Point the app at the test database BEFORE app.db creates its engine.
_base_url = make_url(Settings().database_url)
_test_url = _base_url.set(database=f"{_base_url.database}_test")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
# Tests read invoices with the answer-key extractor and keep uploads in a throwaway folder.
os.environ["AI_PROVIDER"] = "fake"
os.environ["FILE_STORE_DIR"] = tempfile.mkdtemp(prefix="orrfin-test-files-")
get_settings.cache_clear()


def _prepare_test_database() -> str | None:
    """Create, migrate and empty the test database. Returns a skip reason, or None if ready."""
    try:
        admin = create_engine(_base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _test_url.database}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
        admin.dispose()
    except (OperationalError, InterfaceError) as exc:
        if os.environ.get("CI"):
            raise
        return f"Postgres is not running ({type(exc).__name__}); start it with scripts/dev.ps1"

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

    owner = create_engine(_test_url)  # schema owner, not the restricted app role
    with owner.begin() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )).scalars().all()
        conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    owner.dispose()
    return None


_skip_reason = _prepare_test_database()


@pytest.fixture
def owner_engine():
    """Connection as the schema owner, for checks the app role must not be able to do."""
    engine = create_engine(_test_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db() -> Iterator:
    if _skip_reason:
        pytest.skip(_skip_reason)
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


class Factory:
    """Builds orgs and users for one test. Emails are unique per test run."""

    def __init__(self, db):
        self.db = db
        from app.auth.passwords import hash_password

        self._password_hash = hash_password(TEST_PASSWORD)

    def org(self, name: str = "Test Org"):
        from app.models import Org

        org = Org(name=name)
        self.db.add(org)
        self.db.commit()
        return org

    def user(self, org, role: str, *, limit: str = "0", manager=None, name: str | None = None):
        from app.models import User

        user = User(
            org_id=org.id,
            email=f"{role}-{uuid.uuid4().hex[:10]}@test.orrfin.local",
            full_name=name or role.title(),
            password_hash=self._password_hash,
            role=role,
            approval_limit=Decimal(limit),
            manager_id=manager.id if manager else None,
        )
        self.db.add(user)
        self.db.commit()
        return user


@pytest.fixture
def factory(db) -> Factory:
    return Factory(db)


def login(client, user) -> None:
    """Log the test client in as `user` (the session cookie stays on the client)."""
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
