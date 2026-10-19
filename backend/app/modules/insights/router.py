"""HTTP route for the control dashboard (BUILD_PLAN v2.3 change 23).

Money and hours leave as strings (via the audit module's to_jsonable), never as JSON floats.
"""

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.insights import service

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/summary")
def summary(user: CurrentUser, db: DbSession,
            period: Literal["month", "quarter", "all"] = Query("quarter")) -> JSONResponse:
    scope = service.Scope(org_id=user.org_id, user_id=user.id, role=user.role)
    return JSONResponse(to_jsonable(service.summary(db, scope, period)))
