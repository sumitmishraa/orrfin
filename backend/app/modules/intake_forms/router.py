"""HTTP routes for request types and their forms (BUILD_PLAN v3.0 change 40).

Anyone signed in reads the types in use (the new-request form needs them); only an admin saves one.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.modules.audit.service import to_jsonable
from app.modules.intake_forms import service

router = APIRouter(prefix="/request-types", tags=["intake forms"])
admin_only = [Depends(require_roles(*service.EDITOR_ROLES))]


class FieldIn(BaseModel):
    key: str = Field(max_length=40)
    label: str = Field(max_length=120)
    kind: str = Field(max_length=10)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)


class TypeIn(BaseModel):
    key: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    active: bool = True
    fields: list[FieldIn] = Field(default_factory=list, max_length=40)


def _save(db: DbSession, user: CurrentUser, body: TypeIn, type_id: uuid.UUID | None) -> dict[str, Any]:
    request_type = service.save_type(db, user, type_id=type_id, key=body.key, name=body.name,
                                     description=body.description, active=body.active,
                                     fields=[f.model_dump() for f in body.fields])
    db.commit()
    return to_jsonable(service.as_dict(db, request_type))


@router.get("")
def list_types(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable([service.as_dict(db, t) for t in service.list_types(db, user)]))


@router.post("", status_code=201, dependencies=admin_only)
def create_type(body: TypeIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(status_code=201, content=_save(db, user, body, None))


@router.put("/{type_id}", dependencies=admin_only)
def update_type(type_id: uuid.UUID, body: TypeIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(_save(db, user, body, type_id))
