"""Login lockout against password guessing (BUILD_PLAN §9 "Stronger sign-in").

After `login_max_failures` wrong passwords for one email inside the lock window, that email
cannot log in for `login_lock_minutes`, even with the right password.

Design choices:
- Counted per email, whether or not an account exists, so a lockout never reveals which
  emails are real. Only a SHA-256 of the email is stored.
- Time-limited, never permanent: someone who knows an email can lock its owner out for a
  few minutes but cannot keep them out without continuing the attack, which is visible.
- The row is locked while it is updated, so parallel guesses cannot each see "4 failures".
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LoginThrottle


def _key_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def seconds_locked(db: Session, email: str) -> int:
    """How long this email must still wait before it may try again; 0 means it may try now."""
    locked_until = db.scalar(select(LoginThrottle.locked_until).where(LoginThrottle.key_hash == _key_hash(email)))
    if locked_until is None:
        return 0
    remaining = (locked_until - datetime.now(UTC)).total_seconds()
    return max(0, int(remaining) + 1) if remaining > 0 else 0


def record_failure(db: Session, email: str) -> None:
    """Count one wrong password; lock the email when the limit is reached. Caller commits."""
    settings = get_settings()
    now = datetime.now(UTC)
    window = timedelta(minutes=settings.login_lock_minutes)
    key_hash = _key_hash(email)

    db.execute(insert(LoginThrottle).values(key_hash=key_hash, failed_count=0, window_started_at=now)
               .on_conflict_do_nothing(index_elements=["key_hash"]))
    row = db.scalars(select(LoginThrottle).where(LoginThrottle.key_hash == key_hash).with_for_update()).one()

    if now - row.window_started_at > window:
        # Old failures no longer count: a typo last week is not part of an attack today.
        row.failed_count = 0
        row.window_started_at = now
    row.failed_count += 1
    if row.failed_count >= settings.login_max_failures:
        row.locked_until = now + window
        row.failed_count = 0
        row.window_started_at = now


def clear(db: Session, email: str) -> None:
    """A correct password wipes the count. Caller commits."""
    db.execute(delete(LoginThrottle).where(LoginThrottle.key_hash == _key_hash(email)))
