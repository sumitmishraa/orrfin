"""HTTP routes for the Rules page (BUILD_PLAN v2.3 change 24). Everyone reads; only admins edit.

Each edit commits once, together with its audit event (rules/service.py).
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.modules.audit.service import to_jsonable
from app.modules.rules import service

router = APIRouter(prefix="/rules", tags=["rules"])
admin_only = Depends(require_roles(*service.EDITOR_ROLES))


class TierIn(BaseModel):
    min_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    max_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    steps: list[str] = Field(min_length=1, max_length=6)


class TiersIn(BaseModel):
    tiers: list[TierIn] = Field(min_length=1, max_length=service.MAX_TIERS)


class CategoryBuyerIn(BaseModel):
    buyer_id: uuid.UUID | None


@router.get("")
def overview(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.overview(db, user)))


@router.put("/approval-tiers", dependencies=[admin_only])
def replace_tiers(body: TiersIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.replace_tiers(db, user, [service.TierInput(t.min_amount, t.max_amount, t.steps) for t in body.tiers])
    db.commit()
    return JSONResponse(to_jsonable(service.overview(db, user)))


@router.patch("/categories/{category_id}", dependencies=[admin_only])
def set_category_buyer(category_id: uuid.UUID, body: CategoryBuyerIn, user: CurrentUser,
                       db: DbSession) -> JSONResponse:
    service.set_category_buyer(db, user, category_id, body.buyer_id)
    db.commit()
    return JSONResponse(to_jsonable(service.overview(db, user)))
