"""HTTP routes for App Studio (BUILD_PLAN change 49)."""

import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.app_studio import service
from app.modules.audit.service import to_jsonable
from app.modules.intake_forms.router import FieldIn

router = APIRouter(prefix="/app-studio", tags=["app studio"])


class ObjectIn(BaseModel):
    key: str = Field(max_length=40)
    name: str = Field(min_length=1, max_length=120)
    fields: list[FieldIn] = Field(min_length=1, max_length=40)
    approver_role: str = Field(max_length=10)
    list_columns: list[str] = Field(min_length=1, max_length=8)


class RecordIn(BaseModel):
    values: dict[str, Any] = Field(max_length=40)


class DecisionIn(BaseModel):
    decision: str = Field(max_length=10)
    reason: str | None = Field(default=None, max_length=2000)


@router.get("")
def list_objects(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable([service.as_dict(o) for o in service.list_objects(db, user)]))


@router.post("", status_code=201)
def save_object(body: ObjectIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    obj = service.save_object(db, user, key=body.key, name=body.name, fields=[f.model_dump() for f in body.fields],
                              approver_role=body.approver_role, list_columns=body.list_columns)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.as_dict(obj)))


@router.get("/{object_id}/records")
def records(object_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_view(db, user, object_id)))


@router.post("/{object_id}/records", status_code=201)
def create_record(object_id: uuid.UUID, body: RecordIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.create_record(db, user, object_id, body.values)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.list_view(db, user, object_id)))


@router.post("/{object_id}/records/{record_id}/decision")
def decide(object_id: uuid.UUID, record_id: uuid.UUID, body: DecisionIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.decide(db, user, object_id, record_id, body.decision, body.reason)
    db.commit()
    return JSONResponse(to_jsonable(service.list_view(db, user, object_id)))
