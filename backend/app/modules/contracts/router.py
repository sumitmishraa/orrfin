"""HTTP routes for contracts (BUILD_PLAN change 44). Employees only; every check is in the service."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.config import get_settings
from app.modules.audit.service import to_jsonable
from app.modules.contracts import service

router = APIRouter(prefix="/contracts", tags=["contracts"])


class ContractIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    supplier_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None


class TermIn(BaseModel):
    value: str = Field(min_length=1, max_length=500)


class ObligationIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    due_on: date
    owner_id: uuid.UUID


def _show(db, contract) -> JSONResponse:
    return JSONResponse(to_jsonable(service.detail(db, contract)))


@router.get("")
def list_contracts(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_contracts(db, user)))


@router.post("", status_code=201)
def create(body: ContractIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    contract = service.create(db, user, **body.model_dump())
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.detail(db, contract)))


@router.get("/{contract_id}")
def get_contract(contract_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _show(db, service.load(db, user, contract_id))


@router.post("/{contract_id}/file")
def upload(contract_id: uuid.UUID, user: CurrentUser, db: DbSession, file: Annotated[UploadFile, File()]) -> JSONResponse:
    result = service.upload(db, user, contract_id, filename=file.filename or "",
                            data=file.file.read(get_settings().max_upload_bytes + 1))
    db.commit()
    return JSONResponse(to_jsonable({**service.detail(db, service.load(db, user, contract_id)), **result}))


@router.put("/{contract_id}/terms/{field}")
def set_term(contract_id: uuid.UUID, field: str, body: TermIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.set_term(db, user, contract_id, field, body.value)
    db.commit()
    return _show(db, service.load(db, user, contract_id))


@router.post("/{contract_id}/activate")
def activate(contract_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    contract = service.activate(db, user, contract_id)
    db.commit()
    return _show(db, contract)


@router.post("/{contract_id}/obligations", status_code=201)
def add_obligation(contract_id: uuid.UUID, body: ObligationIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.add_obligation(db, user, contract_id, **body.model_dump())
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.detail(db, service.load(db, user, contract_id))))


@router.post("/{contract_id}/obligations/{obligation_id}/done")
def complete_obligation(contract_id: uuid.UUID, obligation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.complete_obligation(db, user, contract_id, obligation_id)
    db.commit()
    return _show(db, service.load(db, user, contract_id))
