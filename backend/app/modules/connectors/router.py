"""HTTP routes for the Connectors page (BUILD_PLAN §4 connector rules, §9; PROMPTS Step 12; ADR 0006).

Admin only, except GET /connectors/active, which every signed-in user may read so screens can name the
ERP ("Draft created in Tally as …"). Saved secrets are write-only: responses carry "set" and the last
four characters, never a value. "Prepare demo data" runs as a job (it may make ~100 ERP calls).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import CATALOGUE, get_adapter, label_for, spec_for
from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.errors import Conflict, NotFound
from app.jobs import enqueue, handler
from app.models import ErpConnection, Job, User
from app.modules.connectors import service
from app.modules.sync.router import JobOut
from app.ports.erp import Capabilities, ConnectionCheck

router = APIRouter(prefix="/connectors", tags=["connectors"])
admin_only = require_roles("admin")


class CredentialsIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict, max_length=10)


def _capabilities(connection: ErpConnection) -> dict[str, Any] | None:
    try:
        caps: Capabilities = get_adapter(connection).capabilities()
    except Exception:  # not built, or live keys missing: the card says so elsewhere
        return None
    return caps.model_dump()


def _card(rows: list[ErpConnection], system: str) -> dict[str, Any]:
    spec = CATALOGUE[system]
    simulated = next((r for r in rows if r.system == system and r.mode == "simulated"), None)
    live = next((r for r in rows if r.system == system and r.mode == "live"), None)
    return {
        "system": system, "name": spec.name, "segment": spec.segment, "live_label": spec.live_label,
        "built": spec.built, "step": spec.step, "signup": spec.signup, "note": spec.note,
        "has_live_mode": spec.has_live_mode,
        "fields": [{"name": f.name, "label": f.label, "secret": f.secret, "help": f.help, "required": f.required,
                    "placeholder": f.placeholder} for f in spec.fields],
        "capabilities": _capabilities(simulated) if spec.built and simulated else None,
        "simulated": service.describe(simulated), "live": service.describe(live),
    }


@router.get("")
def list_connectors(db: DbSession, user: User = Depends(admin_only)) -> list[dict[str, Any]]:
    rows = service.ensure_connections(db, user.org_id)
    db.commit()
    return [_card(rows, system) for system in CATALOGUE]


@router.get("/active")
def active(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    connection = service.active_connection(db, user.org_id)
    db.commit()
    spec = spec_for(connection.system)
    return {"id": connection.id, "system": connection.system, "name": spec.name, "mode": connection.mode,
            "label": label_for(connection), "capabilities": _capabilities(connection)}


@router.put("/{system}/credentials")
def save_credentials(system: str, body: CredentialsIn, db: DbSession,
                     user: User = Depends(admin_only)) -> dict[str, Any]:
    if system not in CATALOGUE:
        raise NotFound("Unknown ERP.")
    row = service.save_credentials(db, user.org_id, system, body.values, user.id)
    db.commit()
    return service.describe(row)


@router.delete("/{system}/credentials")
def remove_credentials(system: str, db: DbSession, user: User = Depends(admin_only)) -> dict[str, Any]:
    service.ensure_connections(db, user.org_id)
    row = db.scalar(select(ErpConnection).where(ErpConnection.org_id == user.org_id, ErpConnection.system == system,
                                               ErpConnection.mode == "live").with_for_update())
    if row is None:
        raise NotFound("No live connection for this ERP.")
    row = service.disconnect(db, row, user.id)
    db.commit()
    return service.describe(row)


@router.post("/connections/{connection_id}/test", response_model=ConnectionCheck)
def test(connection_id: uuid.UUID, db: DbSession, user: User = Depends(admin_only)) -> ConnectionCheck:
    connection = service.get_connection(db, user.org_id, connection_id, lock=True)
    check = service.run_connection_test(db, connection, user.id)
    db.commit()
    return check


@router.post("/connections/{connection_id}/prepare", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def prepare(connection_id: uuid.UUID, db: DbSession, user: User = Depends(admin_only)) -> Job:
    connection = service.get_connection(db, user.org_id, connection_id)
    if connection.mode == "live" and connection.status != "connected":
        raise Conflict("Run 'Test connection' first and fix anything it reports.")
    job = enqueue(db, org_id=user.org_id, kind="erp_prepare", payload={"connection_id": str(connection.id)},
                  created_by=user.id)
    db.commit()
    return job


@router.post("/connections/{connection_id}/activate")
def make_active(connection_id: uuid.UUID, db: DbSession, user: User = Depends(admin_only)) -> dict[str, Any]:
    connection = service.get_connection(db, user.org_id, connection_id, lock=True)
    service.activate(db, connection, user.id)
    db.commit()
    return service.describe(connection)


@handler("erp_prepare")
def run_prepare(db: Session, job: Job) -> dict[str, Any]:
    connection = service.get_connection(db, job.org_id, uuid.UUID(job.payload["connection_id"]), lock=True)
    return service.prepare_demo_data(db, connection, job.created_by).model_dump()
