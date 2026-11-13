"""HTTP routes for the workflow builder (ADR 0010). Admins only: every route is guarded.

Check and Simulate change nothing. Save and Publish commit once, together with their audit event.
"""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.errors import Invalid
from app.modules.audit.service import to_jsonable
from app.modules.workflow_engine import service

router = APIRouter(prefix="/workflow-definitions", tags=["workflow engine"],
                   dependencies=[Depends(require_roles(*service.EDITOR_ROLES))])


class DefinitionIn(BaseModel):
    definition: dict[str, Any]


class SimulateIn(DefinitionIn):
    # Sample facts as text, e.g. {"amount": "75000.00", "category": "Software & SaaS"}.
    facts: dict[str, str] = Field(default_factory=dict, max_length=30)


class DraftIn(DefinitionIn):
    key: str = Field(min_length=3, max_length=60)
    name: str = Field(min_length=1, max_length=120)


def _facts(raw: dict[str, str]) -> dict[str, Any]:
    facts: dict[str, Any] = dict(raw)
    if "amount" in facts:
        try:
            facts["amount"] = Decimal(facts["amount"])
        except InvalidOperation as exc:
            raise Invalid("The sample amount must be a number, for example 75000.00.") from exc
    return facts


@router.get("")
def list_definitions(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_definitions(db, user)))


@router.get("/{definition_id}")
def get_definition(definition_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.get_definition(db, user, definition_id)))


@router.post("/check")
def check(body: DefinitionIn, user: CurrentUser, db: DbSession) -> dict[str, list[str]]:
    return {"problems": service.problems_for(db, user.org_id, body.definition)}


@router.post("/simulate")
def simulate(body: SimulateIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.simulate(db, user, body.definition, _facts(body.facts))))


@router.post("", status_code=201)
def save_draft(body: DraftIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    version = service.save_draft(db, user, key=body.key, name=body.name, definition=body.definition)
    problems = service.problems_for(db, user.org_id, body.definition)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable({
        "definition_id": version.definition_id, "version_id": version.id, "number": version.number,
        "status": version.status, "sha256": version.sha256, "problems": problems}))


@router.post("/versions/{version_id}/publish")
def publish(version_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    version = service.publish(db, user, version_id)
    db.commit()
    return JSONResponse(to_jsonable({"version_id": version.id, "number": version.number,
                                     "status": version.status, "sha256": version.sha256,
                                     "published_at": version.published_at}))
