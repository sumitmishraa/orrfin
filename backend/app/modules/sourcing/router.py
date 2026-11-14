"""HTTP routes for sourcing: `/rfqs` for employees and `/portal/rfqs` for invited suppliers (§9 v3.0).

Amounts travel as decimal strings, never JSON numbers, so nothing passes through a float.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.sourcing import service
from app.modules.suppliers.portal import my_supplier
from app.modules.suppliers.router import CurrentContact

router = APIRouter(prefix="/rfqs", tags=["sourcing"])
portal_router = APIRouter(prefix="/portal/rfqs", tags=["supplier portal"])
MONEY = r"^\d{1,15}(\.\d{1,2})?$"
QTY = r"^\d{1,12}(\.\d{1,3})?$"


class RfqLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    qty: str = Field(pattern=QTY)
    uom: str = Field(default="Nos", max_length=40)


class RfqIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category_id: uuid.UUID
    currency: str = Field(min_length=3, max_length=3)
    closes_at: datetime
    lines: list[RfqLineIn] = Field(min_length=1, max_length=50)
    weights: dict[str, int] | None = None


class InviteIn(BaseModel):
    supplier_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class AwardIn(BaseModel):
    quote_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=2000)


class QuoteLineIn(BaseModel):
    rfq_line_id: uuid.UUID
    rate: str = Field(pattern=MONEY)
    tax_rate: str = Field(pattern=r"^\d{1,3}(\.\d{1,4})?$")


class QuoteIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    freight: str = Field(default="0", pattern=MONEY)
    payment_terms_days: int = Field(ge=0, le=365)
    delivery_days: int = Field(ge=0, le=365)
    valid_until: date
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=50)


def _detail(db, user, rfq) -> JSONResponse:
    return JSONResponse(to_jsonable(service.detail(db, user, rfq)))


@router.get("")
def list_rfqs(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_rfqs(db, user)))


@router.post("", status_code=201)
def create_rfq(body: RfqIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    rfq = service.create_rfq(db, user, title=body.title, category_id=body.category_id, currency=body.currency,
                             closes_at=body.closes_at, lines=[l.model_dump() for l in body.lines], weights=body.weights)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.detail(db, user, rfq)))


@router.get("/{rfq_id}")
def get_rfq(rfq_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _detail(db, user, service.load_rfq(db, user, rfq_id))


@router.post("/{rfq_id}/invites")
def invite(rfq_id: uuid.UUID, body: InviteIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    rfq = service.invite(db, user, rfq_id, body.supplier_ids)
    db.commit()
    return _detail(db, user, rfq)


@router.post("/{rfq_id}/open")
def open_rfq(rfq_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    rfq = service.open_rfq(db, user, rfq_id)
    db.commit()
    return _detail(db, user, rfq)


@router.post("/{rfq_id}/close")
def close_rfq(rfq_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    rfq = service.close_rfq(db, user, rfq_id)
    db.commit()
    return _detail(db, user, rfq)


@router.post("/{rfq_id}/award")
def award(rfq_id: uuid.UUID, body: AwardIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    rfq, request = service.award(db, user, rfq_id, body.quote_id, body.reason)
    db.commit()
    return JSONResponse(to_jsonable({**service.detail(db, user, rfq), "request_id": request.id}))


@portal_router.get("")
def portal_rfqs(contact: CurrentContact, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.portal_rfqs(db, my_supplier(db, contact))))


@portal_router.put("/{rfq_id}/quote")
def portal_quote(rfq_id: uuid.UUID, body: QuoteIn, contact: CurrentContact, db: DbSession) -> JSONResponse:
    supplier = my_supplier(db, contact)
    service.submit_quote(db, supplier, contact.id, rfq_id, currency=body.currency, freight=Decimal(body.freight),
                         payment_terms_days=body.payment_terms_days, delivery_days=body.delivery_days,
                         valid_until=body.valid_until,
                         lines={l.rfq_line_id: (Decimal(l.rate), Decimal(l.tax_rate)) for l in body.lines})
    db.commit()
    return JSONResponse(to_jsonable(service.portal_rfqs(db, supplier)))
