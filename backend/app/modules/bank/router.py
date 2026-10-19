"""HTTP routes for bank statements and reconciliation (BUILD_PLAN v2.4 change 32; PROMPTS Step 26)."""

import uuid

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.bank import service

router = APIRouter(tags=["bank"])


@router.get("/bank-statements")
def view(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.view(db, user)))


@router.post("/bank-statements", status_code=201)
def upload(user: CurrentUser, db: DbSession, file: UploadFile = File(...)) -> JSONResponse:
    data = file.file.read(service.MAX_BYTES + 1)
    service.import_statement(db, user, file.filename or "statement.csv", data)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user)), status_code=201)


@router.post("/bank-lines/{line_id}/accept")
def accept(line_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.accept(db, user, line_id)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user)))


@router.post("/bank-lines/{line_id}/unmatch")
def unmatch(line_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.unmatch(db, user, line_id)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user)))
