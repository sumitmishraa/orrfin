"""The audit trail is append-only and tamper-evident (BUILD_PLAN §5 grants; §11 M1 and M5)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.modules.audit.service import record_event, verify_chain


def _two_events(db, factory):
    org = factory.org()
    entity_id = uuid.uuid4()
    for action in ("created", "submitted"):
        record_event(db, org_id=org.id, entity_type="test", entity_id=entity_id,
                     actor_id=None, action=action, payload={"amount": "10.00"})
    db.commit()
    return entity_id


def test_app_role_can_insert_and_read_audit_events(db, factory):
    entity_id = _two_events(db, factory)

    assert verify_chain(db, entity_id)


@pytest.mark.parametrize("statement", [
    "UPDATE audit_events SET action = 'tampered' WHERE entity_id = :id",
    "DELETE FROM audit_events WHERE entity_id = :id",
])
def test_app_role_cannot_update_or_delete_audit_events(db, factory, statement):
    entity_id = _two_events(db, factory)

    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text(statement), {"id": entity_id})
    db.rollback()


def test_a_tampered_event_breaks_the_hash_chain(db, factory, owner_engine):
    entity_id = _two_events(db, factory)

    # Only the schema owner can do this; it simulates someone editing the database directly.
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET payload = '{\"amount\": \"1.00\"}' "
                          "WHERE entity_id = :id AND seq = 1"), {"id": entity_id})

    assert not verify_chain(db, entity_id)
