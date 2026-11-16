"""HTTP routes for Orrfin POs built from approved needs (Step 42, ADR 0012; BUILD_PLAN §8, §9).

Rules live in service.py; these routes translate HTTP to service calls and commit once per action.
Every query is scoped to the signed-in user's org; another org's PO is "not found".
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.ordering import service

router = APIRouter(prefix="/ordering", tags=["ordering"])

Rate = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


class PoLineIn(BaseModel):
    item_code: str = Field(min_length=1, max_length=140)
    rate: Rate
    request_line_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=20)
    hsn: str | None = Field(default=None, max_length=10)


class PoCreate(BaseModel):
    vendor_id: uuid.UUID
    lines: list[PoLineIn] = Field(min_length=1, max_length=100)
    needed_by: date | None = None
    note_to_vendor: str = Field(default="", max_length=2000)


class LineChangeIn(BaseModel):
    id: uuid.UUID
    item_code: str | None = Field(default=None, max_length=140)
    description: str | None = Field(default=None, max_length=300)
    rate: Rate | None = None
    hsn: str | None = Field(default=None, max_length=10)


class PoEdit(BaseModel):
    vendor_id: uuid.UUID | None = None
    needed_by: date | None = None
    note_to_vendor: str | None = Field(default=None, max_length=2000)
    lines: list[LineChangeIn] = Field(default_factory=list, max_length=100)


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "return"]
    reason: str | None = Field(default=None, max_length=2000)


class SendIn(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    note: str | None = Field(default=None, max_length=2000)


def _json(value: object, code: int = status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(to_jsonable(value), status_code=code)


def _show(db, user, po, code: int = status.HTTP_200_OK) -> JSONResponse:
    db.commit()
    return _json(service.detail(db, user, po), code)


@router.get("/needs")
def approved_needs(user: CurrentUser, db: DbSession) -> JSONResponse:
    """Approved need lines not yet on a purchase order."""
    return _json(service.open_needs(db, user))


@router.get("/items")
def items(user: CurrentUser, db: DbSession) -> JSONResponse:
    """ERP item codes with the last price paid (from the mirrored ERP purchase orders)."""
    return _json(service.item_catalog(db, user))


@router.get("/pos")
def list_pos(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.summaries(db, user))


@router.post("/pos")
def create_po(body: PoCreate, user: CurrentUser, db: DbSession) -> JSONResponse:
    po = service.create_po(db, user, vendor_id=body.vendor_id, needed_by=body.needed_by,
                           note_to_vendor=body.note_to_vendor,
                           lines=[service.PoLineInput(**line.model_dump()) for line in body.lines])
    return _show(db, user, po, status.HTTP_201_CREATED)


@router.get("/pos/{po_id}")
def get_po(po_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.detail(db, user, service.load_po(db, user, po_id)))


@router.patch("/pos/{po_id}")
def edit_po(po_id: uuid.UUID, body: PoEdit, user: CurrentUser, db: DbSession) -> JSONResponse:
    po = service.update_po(db, user, po_id, vendor_id=body.vendor_id, needed_by=body.needed_by,
                           note_to_vendor=body.note_to_vendor,
                           lines=[service.LineChange(**line.model_dump()) for line in body.lines])
    return _show(db, user, po)


@router.post("/pos/{po_id}/cancel")
def cancel_po(po_id: uuid.UUID, body: ReasonIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _show(db, user, service.cancel_po(db, user, po_id, body.reason))


@router.post("/pos/{po_id}/submit")
def submit_po(po_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _show(db, user, service.submit_po(db, user, po_id))


@router.post("/pos/{po_id}/approvals/{step}/decision")
def decide(po_id: uuid.UUID, step: int, body: DecisionIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _show(db, user, service.decide_po(db, user, po_id, step, body.decision, body.reason))


@router.get("/pos/{po_id}/vendor-message")
def vendor_message(po_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    """The email and WhatsApp text that "Send to vendor" will record. Nothing is sent."""
    po = service.load_po(db, user, po_id)
    return _json(service.compose(db, po))


@router.post("/pos/{po_id}/send")
def send(po_id: uuid.UUID, body: SendIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    """Record the PO as sent to the vendor (simulated email with the PDF attached)."""
    return _show(db, user, service.send_po(db, user, po_id, to=body.to, note=body.note))
