"""HTTP routes for simulated vendor cards (BUILD_PLAN change 46). Amounts travel as decimal strings."""

import uuid
from decimal import Decimal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.cards import service

router = APIRouter(prefix="/cards", tags=["vendor cards"])
MONEY = r"^\d{1,15}(\.\d{1,2})?$"


class IssueIn(BaseModel):
    request_id: uuid.UUID
    limit: str = Field(pattern=MONEY)
    days: int = Field(default=30, ge=1, le=service.MAX_DAYS)
    merchant_lock: str | None = Field(default=None, max_length=120)


class ChargeIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount: str = Field(pattern=MONEY)


class StatusIn(BaseModel):
    status: str = Field(max_length=8)


def _card(db, card) -> JSONResponse:
    return JSONResponse(to_jsonable(service.as_dict(db, card)))


@router.get("")
def list_cards(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable([service.as_dict(db, c) for c in service.list_cards(db, user)]))


@router.post("", status_code=201)
def issue(body: IssueIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    card = service.issue(db, user, request_id=body.request_id, limit=Decimal(body.limit), days=body.days,
                         merchant_lock=body.merchant_lock)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.as_dict(db, card)))


@router.get("/{card_id}")
def get_card(card_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _card(db, service.load(db, user, card_id))


@router.post("/{card_id}/simulate-charge")
def charge(card_id: uuid.UUID, body: ChargeIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.simulate_charge(db, user, card_id, merchant=body.merchant, amount=Decimal(body.amount))
    db.commit()
    return _card(db, service.load(db, user, card_id))


@router.put("/{card_id}/status")
def set_status(card_id: uuid.UUID, body: StatusIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    card = service.set_status(db, user, card_id, body.status)
    db.commit()
    return _card(db, card)
