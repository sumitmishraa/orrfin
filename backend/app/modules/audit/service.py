"""Write and verify audit events (BUILD_PLAN §2 audit trail, §5 audit_events, §11 M5 hash chain).

Every state change in Orrfin calls `record_event` inside the same database transaction
as the change itself, so a change without its audit row can never be committed.
Each entity has its own chain: event N stores the hash of event N-1, so editing or
deleting any past event breaks `verify_chain`.
"""

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def to_jsonable(value: Any) -> Any:
    """Make a payload JSON-safe without floats: Decimal and dates become strings."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _event_hash(fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_fields(event: AuditEvent) -> dict[str, Any]:
    return {
        "org_id": str(event.org_id),
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "seq": event.seq,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "action": event.action,
        "payload": event.payload,
        "prev_hash": event.prev_hash,
    }


def record_event(
    db: Session,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one event to the entity's chain. The caller commits (same transaction as the change).

    Callers lock the entity row first (SELECT ... FOR UPDATE), so two writers can't
    take the same seq; the unique (entity_id, seq) constraint is the backstop.
    """
    last = db.execute(
        select(AuditEvent.seq, AuditEvent.hash)
        .where(AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    ).first()
    event = AuditEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        seq=(last.seq + 1) if last else 1,
        actor_id=actor_id,
        action=action,
        payload=to_jsonable(payload or {}),
        prev_hash=last.hash if last else None,
    )
    event.hash = _event_hash(_hash_fields(event))
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, entity_id: uuid.UUID) -> bool:
    """True if every event's hash and back-link are intact, with no gap in seq."""
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == entity_id).order_by(AuditEvent.seq)
    ).all()
    prev_hash = None
    for expected_seq, event in enumerate(events, start=1):
        if event.seq != expected_seq or event.prev_hash != prev_hash:
            return False
        if event.hash != _event_hash(_hash_fields(event)):
            return False
        prev_hash = event.hash
    return True


def count_events(db: Session, entity_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(AuditEvent.entity_id == entity_id)) or 0
