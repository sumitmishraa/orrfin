"""Connectors: which ERP an org is plugged into, and how (BUILD_PLAN §4, §5 erp_connections, §9; ADR 0004, 0006).

Owns the erp_connections rows and every rule about them:
- each org always has exactly one *active* connection (simulated ERPNext by default);
- a live connection can only be made active after a passing "Test connection";
- credentials are validated (required fields, allowed hosts) and encrypted before they touch the database;
  a blank secret field on re-save keeps the stored value, so the browser never needs to see it;
- every change is audited in the same transaction, and audit payloads name fields, never values.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import (
    CATALOGUE,
    DEFAULT_SYSTEM,
    get_adapter,
    label_for,
    secret_values,
    sim_state_path,
    spec_for,
)
from app.adapters.sim_store import SimStore
from app.errors import Conflict, Invalid, NotFound
from app.models import ErpConnection
from app.modules.audit.service import record_event
from app.ports.erp import ConnectionCheck, ErpError, SeedReport
from app.security.outbound import UrlNotAllowed, check_base_url, redact
from app.security.secrets import SecretsUnavailable, decrypt_credentials, encrypt_credentials
from app.security.secrets import describe as describe_values

ENTITY = "erp_connection"
ERP_FAILURES = (ErpError, LookupError, UrlNotAllowed, SecretsUnavailable)


def _audit(db: Session, connection: ErpConnection, actor_id: uuid.UUID | None, action: str,
           payload: dict[str, Any]) -> None:
    record_event(db, org_id=connection.org_id, entity_type=ENTITY, entity_id=connection.id, actor_id=actor_id,
                 action=action, payload={"system": connection.system, "mode": connection.mode, **payload})


def ensure_connections(db: Session, org_id: uuid.UUID) -> list[ErpConnection]:
    """One simulated row per catalogue ERP, and one active connection. Safe to call on every request."""
    rows = list(db.scalars(select(ErpConnection).where(ErpConnection.org_id == org_id)))
    have = {(r.system, r.mode) for r in rows}
    for system in CATALOGUE:
        if (system, "simulated") not in have:
            row = ErpConnection(org_id=org_id, system=system, mode="simulated", is_active=False,
                                status="connected" if CATALOGUE[system].built else "not_connected")
            db.add(row)
            rows.append(row)
        else:
            # A connector built in a later step becomes usable without a migration.
            row = next(r for r in rows if r.system == system and r.mode == "simulated")
            if CATALOGUE[system].built and row.status == "not_connected":
                row.status = "connected"
    if not any(r.is_active for r in rows):
        default = next(r for r in rows if r.system == DEFAULT_SYSTEM and r.mode == "simulated")
        default.is_active = True
    db.flush()
    return rows


def active_connection(db: Session, org_id: uuid.UUID) -> ErpConnection:
    row = db.scalar(select(ErpConnection).where(ErpConnection.org_id == org_id, ErpConnection.is_active))
    if row is None:
        ensure_connections(db, org_id)
        row = db.scalar(select(ErpConnection).where(ErpConnection.org_id == org_id, ErpConnection.is_active))
    return row


def get_connection(db: Session, org_id: uuid.UUID, connection_id: uuid.UUID, *, lock: bool = False) -> ErpConnection:
    query = select(ErpConnection).where(ErpConnection.id == connection_id, ErpConnection.org_id == org_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFound("Connection not found.")
    return row


def _live_row(db: Session, org_id: uuid.UUID, system: str) -> ErpConnection:
    row = db.scalar(select(ErpConnection).where(ErpConnection.org_id == org_id, ErpConnection.system == system,
                                               ErpConnection.mode == "live").with_for_update())
    if row is None:
        row = ErpConnection(org_id=org_id, system=system, mode="live", is_active=False, status="not_connected")
        db.add(row)
        db.flush()
    return row


def save_credentials(db: Session, org_id: uuid.UUID, system: str, values: dict[str, str],
                     actor_id: uuid.UUID) -> ErpConnection:
    spec = spec_for(system)
    if not spec.built or not spec.has_live_mode:
        raise Conflict(f"{spec.name} has no live connection in this prototype.")
    unknown = set(values) - {f.name for f in spec.fields}
    if unknown:
        raise Invalid(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    ensure_connections(db, org_id)
    row = _live_row(db, org_id, system)
    try:
        stored = decrypt_credentials(row.credentials_encrypted)
    except SecretsUnavailable:
        stored = {}  # the key changed: start again with what was just typed
    merged: dict[str, str] = {}
    for f in spec.fields:
        typed = (values.get(f.name) or "").strip()
        # A field left blank on re-save keeps the stored value, so the browser never has to hold a secret.
        merged[f.name] = typed or stored.get(f.name, "")
        if f.required and not merged[f.name]:
            raise Invalid(f"{f.label} is required.")
    if merged.get("url"):
        try:
            merged["url"] = check_base_url(merged["url"], spec.host_policy)
        except UrlNotAllowed as exc:
            raise Invalid(str(exc)) from None
    if spec.finish_setup is not None:
        # e.g. Zoho: trade the one-time code for a refresh token now, so the code is never stored.
        try:
            merged = spec.finish_setup(merged)
        except (ErpError, LookupError) as exc:
            raise Invalid(redact(str(exc), secret_values(spec, merged))) from None
    try:
        row.credentials_encrypted = encrypt_credentials(merged)
    except SecretsUnavailable as exc:
        raise Conflict(str(exc)) from None
    # New keys must be tested again before this connection can be (or stay) the active one.
    row.status, row.last_error, row.last_check = "not_connected", None, None
    if row.is_active:
        _fall_back_to_simulated(db, row, actor_id, reason="credentials changed")
    _audit(db, row, actor_id, "erp_credentials_saved", {"fields_set": sorted(k for k, v in merged.items() if v)})
    return row


def _fall_back_to_simulated(db: Session, row: ErpConnection, actor_id: uuid.UUID | None, reason: str) -> None:
    simulated = db.scalar(select(ErpConnection).where(ErpConnection.org_id == row.org_id,
                                                     ErpConnection.system == row.system,
                                                     ErpConnection.mode == "simulated"))
    row.is_active = False
    db.flush()  # the partial unique index allows only one active row at any moment
    simulated.is_active = True
    db.flush()
    _audit(db, simulated, actor_id, "erp_connection_activated", {"reason": reason})


def safe_message(connection: ErpConnection, message: str) -> str:
    """Strip any of this connection's own secrets from an ERP or library message before storing it."""
    try:
        values = decrypt_credentials(connection.credentials_encrypted)
    except SecretsUnavailable:
        values = {}
    return redact(message, secret_values(spec_for(connection.system), values))[:500]


def run_connection_test(db: Session, connection: ErpConnection, actor_id: uuid.UUID) -> ConnectionCheck:
    try:
        check = get_adapter(connection).test_connection()
    except ERP_FAILURES as exc:
        check = ConnectionCheck(ok=False, steps=[])
        connection.last_error = safe_message(connection, str(exc))
    else:
        connection.last_error = None if check.ok else next((s.detail for s in check.steps if not s.ok), None)
        if connection.last_error:
            connection.last_error = safe_message(connection, connection.last_error)
    for step in check.steps:
        step.detail = safe_message(connection, step.detail)
    connection.status = "connected" if check.ok else "error"
    connection.last_checked_at = datetime.now(UTC)
    connection.last_check = check.model_dump()
    _audit(db, connection, actor_id, "erp_connection_tested", {"ok": check.ok})
    return check


def prepare_demo_data(db: Session, connection: ErpConnection, actor_id: uuid.UUID | None) -> SeedReport:
    """Simulated: reset to the canonical fixtures. Live: create the canonical dataset in the ERP (idempotent)."""
    if connection.mode == "simulated":
        SimStore(sim_state_path(connection)).reset()
        report = SeedReport(created={}, existing={}, notes=["Simulated ERP reset to the demo dataset."])
    else:
        if connection.status != "connected":
            raise Conflict("Run 'Test connection' first and fix anything it reports.")
        try:
            report = get_adapter(connection).seed_demo_data()
        except ERP_FAILURES as exc:
            raise Conflict(f"Preparing demo data stopped: {safe_message(connection, str(exc))}") from None
    _audit(db, connection, actor_id, "erp_demo_data_prepared", report.model_dump())
    return report


def activate(db: Session, connection: ErpConnection, actor_id: uuid.UUID) -> ErpConnection:
    spec = spec_for(connection.system)
    if not spec.built:
        raise Conflict(f"The {spec.name} connector arrives in Step {spec.step}.")
    if connection.mode == "live" and connection.status != "connected":
        raise Conflict("Test the connection successfully before making it active.")
    if connection.is_active:
        return connection
    previous = db.scalar(select(ErpConnection).where(ErpConnection.org_id == connection.org_id,
                                                    ErpConnection.is_active).with_for_update())
    if previous is not None:
        previous.is_active = False
        db.flush()  # the partial unique index allows only one active row at any moment
    connection.is_active = True
    db.flush()
    _audit(db, connection, actor_id, "erp_connection_activated",
           {"previous": f"{previous.system}/{previous.mode}" if previous else None})
    return connection


def disconnect(db: Session, connection: ErpConnection, actor_id: uuid.UUID) -> ErpConnection:
    """Forget a live connection's keys. If it was active, the same ERP's simulated mode takes over."""
    if connection.mode != "live":
        raise Conflict("Only live connections hold keys.")
    if connection.is_active:
        _fall_back_to_simulated(db, connection, actor_id, reason="live connection disconnected")
    connection.credentials_encrypted = None
    connection.status, connection.last_check, connection.last_error = "not_connected", None, None
    _audit(db, connection, actor_id, "erp_credentials_removed", {})
    return connection


def describe(connection: ErpConnection | None) -> dict[str, Any] | None:
    """What the Connectors page may show about one connection. Never a secret value."""
    if connection is None:
        return None
    spec = spec_for(connection.system)
    try:
        values = decrypt_credentials(connection.credentials_encrypted)
        fields = describe_values({f.name: values.get(f.name, "") for f in spec.fields}, spec.secret_fields)
        key_problem = None
    except SecretsUnavailable as exc:
        fields, key_problem = {}, str(exc)
    return {
        "id": connection.id, "mode": connection.mode, "label": label_for(connection),
        "is_active": connection.is_active, "status": connection.status,
        "last_checked_at": connection.last_checked_at, "last_check": connection.last_check,
        "last_error": connection.last_error or key_problem, "fields": fields,
    }
