"""Login sessions (BUILD_PLAN §3 Auth: email + password, server-side session cookie).

The browser holds only a random token; the database stores its SHA-256, so a leaked
database backup cannot be replayed as a login.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.config import get_settings
from app.models import User, UserSession


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    # verify_password runs even for an unknown email, so timing doesn't reveal accounts.
    if not verify_password(user.password_hash if user else None, password):
        return None
    if user is None or not user.active:
        return None
    return user


def start_session(db: Session, user: User) -> str:
    """Create a session row and return the raw token for the cookie. Caller commits."""
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        org_id=user.org_id,
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_hours),
    ))
    return token


def user_for_token(db: Session, token: str) -> User | None:
    row = db.execute(
        select(User, UserSession.expires_at)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == _token_hash(token))
    ).first()
    if row is None:
        return None
    user, expires_at = row
    if expires_at <= datetime.now(UTC) or not user.active:
        return None
    return user


def end_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
