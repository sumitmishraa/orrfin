"""HTTP routes for the month-end close cockpit (BUILD_PLAN v2.4 change 32; PROMPTS Step 26)."""

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.close import service

router = APIRouter(prefix="/close", tags=["close"])


class CloseIn(BaseModel):
    notes: dict[str, str] = Field(default_factory=dict)  # checklist key → why it is acceptable to close anyway


class ReopenIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/current")
def current(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.view(db, user, service.current_period())))


@router.get("/{period}")
def view(period: str, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.view(db, user, period)))


@router.get("/{period}/received-not-invoiced.csv")
def rni_csv(period: str, user: CurrentUser, db: DbSession) -> Response:
    rows = service.view(db, user, period)["received_not_invoiced"]
    return Response(service.received_not_invoiced_csv(rows), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="received-not-invoiced-{period}.csv"'})


@router.post("/{period}/close")
def close(period: str, body: CloseIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.close(db, user, period, body.notes)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user, period)))


@router.post("/{period}/reopen")
def reopen(period: str, body: ReopenIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.reopen(db, user, period, body.reason)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user, period)))
