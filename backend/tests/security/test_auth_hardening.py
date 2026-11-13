"""Attack tests for sign-in and the browser boundary (BUILD_PLAN §9 "Stronger sign-in", v3.0 change 50).

Each test is something an attacker would try: a forged request from another website, guessing a
password many times, reusing an old session, or framing the app. They must keep failing safely.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from tests.conftest import TEST_PASSWORD

SESSION_COOKIE = "orrfin_session"


@pytest.fixture
def outside_client(db):
    """A client that sends nothing the Orrfin web app adds, like a form on someone else's website."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _login(client, email: str, password: str = TEST_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


# --- Cross-site request forgery -------------------------------------------------------------

def test_a_write_without_the_app_header_is_refused(outside_client, factory):
    user = factory.user(factory.org(), "finance")

    response = _login(outside_client, user.email)

    assert response.status_code == 403
    assert SESSION_COOKIE not in response.cookies


def test_a_write_from_another_website_is_refused_even_with_the_header(client, factory):
    user = factory.user(factory.org(), "finance")

    response = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD},
                           headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_a_write_from_the_web_apps_own_address_is_accepted(client, factory):
    user = factory.user(factory.org(), "finance")

    response = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD},
                           headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200


def test_reading_needs_no_app_header(outside_client):
    assert outside_client.get("/health").status_code == 200


# --- Password guessing ----------------------------------------------------------------------

def test_five_wrong_passwords_lock_the_login_even_for_the_right_password(client, factory):
    user = factory.user(factory.org(), "requester")

    for _ in range(5):
        assert _login(client, user.email, "wrong-password").status_code == 401
    locked = _login(client, user.email)

    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert SESSION_COOKIE not in locked.cookies


def test_an_unknown_email_locks_the_same_way_so_lockout_reveals_no_accounts(client):
    email = "nobody-lockout@test.orrfin.local"

    statuses = [_login(client, email, "x").status_code for _ in range(6)]

    assert statuses == [401, 401, 401, 401, 401, 429]


def test_a_successful_login_clears_earlier_failures(client, factory):
    user = factory.user(factory.org(), "requester")

    for _ in range(4):
        _login(client, user.email, "wrong-password")
    assert _login(client, user.email).status_code == 200
    statuses = [_login(client, user.email, "wrong-password").status_code for _ in range(4)]

    assert statuses == [401, 401, 401, 401]


def test_the_lock_ends_after_its_time(client, factory, db):
    from app.models import LoginThrottle

    user = factory.user(factory.org(), "requester")
    for _ in range(5):
        _login(client, user.email, "wrong-password")
    assert _login(client, user.email).status_code == 429

    # Move the clock: the lock and its counting window both ended a moment ago.
    past = datetime.now(UTC) - timedelta(hours=1)
    db.execute(update(LoginThrottle).values(locked_until=past, window_started_at=past))
    db.commit()

    assert _login(client, user.email).status_code == 200


# --- Sessions -------------------------------------------------------------------------------

def test_logging_in_again_ends_the_session_the_browser_already_had(client, outside_client, factory):
    user = factory.user(factory.org(), "buyer")
    assert _login(client, user.email).status_code == 200
    old_token = client.cookies[SESSION_COOKIE]

    assert _login(client, user.email).status_code == 200
    new_token = client.cookies[SESSION_COOKIE]

    assert new_token != old_token
    outside_client.cookies.set(SESSION_COOKIE, old_token)
    assert outside_client.get("/auth/me").status_code == 401


# --- Browser protections --------------------------------------------------------------------

def test_every_answer_carries_the_browser_protection_headers(client, factory):
    user = factory.user(factory.org(), "buyer")
    _login(client, user.email)

    headers = client.get("/auth/me").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    # SAMEORIGIN, not DENY: the invoice page shows the uploaded file in a frame on Orrfin's own site.
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert headers["Referrer-Policy"] == "same-origin"
    assert headers["Cache-Control"] == "no-store"


# --- Deployment settings --------------------------------------------------------------------

def test_a_deployed_server_refuses_to_start_with_laptop_settings():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError) as refusal:
        Settings(_env_file=None, app_env="production", session_cookie_secure=False,
                 orrfin_secret_key=None, ai_provider="fake")

    message = str(refusal.value)
    assert "SESSION_COOKIE_SECURE" in message and "ORRFIN_SECRET_KEY" in message
    assert "https://" in message and "AI_PROVIDER=fake" in message


def test_a_deployed_server_starts_with_safe_settings():
    from app.config import Settings

    settings = Settings(_env_file=None, app_env="production", session_cookie_secure=True,
                        orrfin_secret_key="k", ai_provider="gemini",
                        cors_origins=["https://app.orrfin.example"], public_web_url="https://app.orrfin.example")

    assert settings.app_env == "production"
