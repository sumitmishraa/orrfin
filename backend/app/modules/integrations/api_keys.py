"""Personal API keys (BUILD_PLAN v3.0 §5 `api_keys`, §9).

A key belongs to one user and can never do more than that user: whoever presents it is treated
as that person, with that person's role and org. The key is shown once, when it is made; only
its SHA-256 is stored, so a copy of the database does not contain a usable key. Keys always
expire, can be revoked at any time, and stop working when their owner is switched off.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Invalid, NotFound
from app.models import ApiKey, User
from app.modules.audit.service import record_event

KEY_PREFIX = "orf_"
SCOPES = ("read",)  # the MCP server and read API (Step 35) accept "read"; nothing can write with a key yet
MAX_ACTIVE_KEYS = 10
MAX_DAYS = 365


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def as_dict(key: ApiKey) -> dict[str, Any]:
    """What may be shown about a key. Never the key or its hash."""
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "scopes": key.scopes, "user_id": key.user_id,
            "created_at": key.created_at, "last_used_at": key.last_used_at, "expires_at": key.expires_at,
            "revoked": key.revoked_at is not None}


def _usable(now: datetime):
    return (ApiKey.revoked_at.is_(None)) & (ApiKey.expires_at > now)


def create_key(db: Session, user: User, *, name: str, days: int) -> tuple[ApiKey, str]:
    """Make a key for the signed-in user. Returns the row and the key itself, which is not kept."""
    name = name.strip()
    if not name:
        raise Invalid("Give the key a name, so you know later what uses it.")
    if not 1 <= days <= MAX_DAYS:
        raise Invalid(f"A key lasts between 1 and {MAX_DAYS} days.")
    now = datetime.now(UTC)
    active = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id, _usable(now)))
    if (active or 0) >= MAX_ACTIVE_KEYS:
        raise Conflict(f"You already have {MAX_ACTIVE_KEYS} working keys. Revoke one first.")
    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(id=uuid.uuid4(), org_id=user.org_id, user_id=user.id, name=name[:120], prefix=raw_key[:10],
                 key_hash=_hash(raw_key), scopes=list(SCOPES), expires_at=now + timedelta(days=days))
    db.add(key)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="api_key", entity_id=key.id, actor_id=user.id, action="created",
                 payload={"name": key.name, "prefix": key.prefix, "expires_at": key.expires_at.isoformat()})
    return key, raw_key


def list_keys(db: Session, user: User) -> list[ApiKey]:
    """A person sees their own keys; an admin sees every key in the org (to revoke a leaked one)."""
    query = select(ApiKey).where(ApiKey.org_id == user.org_id).order_by(ApiKey.created_at.desc())
    if user.role != "admin":
        query = query.where(ApiKey.user_id == user.id)
    return list(db.scalars(query))


def revoke_key(db: Session, user: User, key_id: uuid.UUID) -> ApiKey:
    query = select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == user.org_id).with_for_update()
    if user.role != "admin":
        query = query.where(ApiKey.user_id == user.id)
    key = db.scalar(query)
    if key is None:
        raise NotFound("Key not found.")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        record_event(db, org_id=user.org_id, entity_type="api_key", entity_id=key.id, actor_id=user.id,
                     action="revoked", payload={"name": key.name, "prefix": key.prefix})
    return key


def user_for_key(db: Session, raw_key: str | None) -> User | None:
    """The active user a working key belongs to, or None. The lookup is by hash, so timing reveals nothing useful."""
    if not raw_key or not raw_key.startswith(KEY_PREFIX) or len(raw_key) > 200:
        return None
    now = datetime.now(UTC)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(raw_key), _usable(now)))
    if key is None:
        return None
    user = db.scalar(select(User).where(User.id == key.user_id, User.org_id == key.org_id, User.active))
    if user is None:
        return None
    key.last_used_at = now
    return user
