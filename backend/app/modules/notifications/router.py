"""HTTP routes for the notification bell. Every route acts on the signed-in user's own rows only."""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.notifications import service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def inbox(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.inbox(db, user)))


@router.post("/read-all")
def read_all(user: CurrentUser, db: DbSession) -> dict[str, int]:
    changed = service.mark_read(db, user)
    db.commit()
    return {"marked_read": changed}


@router.post("/{notification_id}/read")
def read_one(notification_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, int]:
    changed = service.mark_read(db, user, notification_id)
    db.commit()
    return {"marked_read": changed}
