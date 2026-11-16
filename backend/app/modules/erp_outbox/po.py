"""Draft purchase orders through the outbox (BUILD_PLAN §8 "Draft Purchase Orders"; PROMPTS Steps 15 and 42).

Same outbox, states and lookup-before-retry as bills (service.py); only the key and the payload differ.
Two sources of a draft PO:
- a request priced by its buyer ("buyer_first" orgs, Step 15):
  key = sha256(org_id|request_id|"purchase_order"), one PO per approved request;
- an Orrfin PO that procurement built from several approved needs ("need_first" orgs, Step 42, ADR 0012):
  key = sha256(org_id|order_po_id|"purchase_order"), one ERP PO for all the needs on it.
push   = the ERP's draft PO (ERPNext: Purchase Order, docstatus 0) carrying the key in its Orrfin Ref field;
lookup = find_po(key).
CONFIRMED → request `po_drafted` (Step 15). A person submits the PO inside the ERP; the next pull sync sees
it, linked by the key (origin = orrfin), and the request becomes `po_open` (modules/sync).
"""

import hashlib
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter, spec_for
from app.erp_demo.canonical import IST
from app.jobs import enqueue
from app.models import (
    ErpConnection,
    ErpOutbox,
    OrderPo,
    OrderPoLine,
    OrderPoLineSource,
    PurchaseRequest,
    RequestLine,
    Vendor,
)
from app.modules.audit.service import record_event
from app.ports.erp import DraftLine, DraftPo

DEFAULT_LEAD_DAYS = 14  # schedule date when the request has no "needed by"


def po_key(request: PurchaseRequest) -> str:
    return hashlib.sha256(f"{request.org_id}|{request.id}|purchase_order".encode("utf-8")).hexdigest()


def order_po_key(order: OrderPo) -> str:
    return hashlib.sha256(f"{order.org_id}|{order.id}|purchase_order".encode("utf-8")).hexdigest()


def vendor_unavailable_reason(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    """Why a draft PO to this vendor can't go to the ERP, or None. Shown on the request or PO page."""
    from app.modules.erp_outbox.service import CONFIG_FAILURES

    vendor = db.get(Vendor, vendor_id) if vendor_id else None
    if vendor is None:
        return "No ERP vendor was chosen, so there is nobody to order from."
    from app.modules.suppliers.service import hold_reason_for_vendor  # local import: suppliers imports notifications

    hold = hold_reason_for_vendor(db, org_id, vendor.id)
    if hold:
        return hold  # §6e: a critical-risk supplier gets no new PO until a reviewer clears the hold
    connection = db.get(ErpConnection, vendor.erp_connection_id)
    name = spec_for(connection.system).name
    if not connection.is_active:
        return (f"The vendor comes from {name} ({connection.mode}), which is no longer the active ERP. "
                "Pick the vendor again from the active ERP.")
    try:
        caps = get_adapter(connection).capabilities()
    except CONFIG_FAILURES as exc:
        return f"{name} isn't ready: {exc}"
    if not caps.can_write_po:
        return caps.write_note or f"{name} can't hold draft purchase orders from Orrfin."
    return None


def po_unavailable_reason(db: Session, request: PurchaseRequest) -> str | None:
    return vendor_unavailable_reason(db, request.org_id, request.vendor_id)


def _queue(db: Session, *, org_id: uuid.UUID, vendor_id: uuid.UUID, key: str, actor_id: uuid.UUID,
           request_id: uuid.UUID | None = None, order_po_id: uuid.UUID | None = None) -> ErpOutbox:
    from app.modules.erp_outbox.service import _audit, _erp_name

    existing = db.scalar(select(ErpOutbox).where(ErpOutbox.idempotency_key == key))
    if existing is not None:
        return existing
    vendor = db.get(Vendor, vendor_id)
    row = ErpOutbox(org_id=org_id, erp_connection_id=vendor.erp_connection_id, idempotency_key=key,
                    doc_type="purchase_order", request_id=request_id, order_po_id=order_po_id, state="PENDING")
    db.add(row)
    db.flush()
    enqueue(db, org_id=org_id, kind="erp_push", payload={"outbox_id": str(row.id)}, created_by=actor_id)
    _audit(db, row, actor_id, "erp_draft_queued",
           {"request_id": request_id, "order_po_id": order_po_id, "erp": _erp_name(db, row)})
    return row


def queue_po(db: Session, request: PurchaseRequest, actor_id: uuid.UUID) -> ErpOutbox | None:
    """Called in the same transaction as the request's final approval (§8 "Trigger")."""
    if po_unavailable_reason(db, request):
        return None
    return _queue(db, org_id=request.org_id, vendor_id=request.vendor_id, key=po_key(request), actor_id=actor_id,
                  request_id=request.id)


def queue_order_po(db: Session, order: OrderPo, actor_id: uuid.UUID) -> ErpOutbox | None:
    """Called in the same transaction as the Orrfin PO's approval (§8 "Trigger")."""
    if vendor_unavailable_reason(db, order.org_id, order.vendor_id):
        return None
    return _queue(db, org_id=order.org_id, vendor_id=order.vendor_id, key=order_po_key(order), actor_id=actor_id,
                  order_po_id=order.id)


def build_draft_po(db: Session, row: ErpOutbox) -> DraftPo:
    if row.order_po_id is not None:
        return _build_from_order(db, row)
    request = db.get(PurchaseRequest, row.request_id)
    vendor = db.get(Vendor, request.vendor_id)
    today: date = datetime.now(IST).date()
    lines = db.scalars(select(RequestLine).where(RequestLine.request_id == request.id)
                       .order_by(RequestLine.line_no)).all()
    return DraftPo(
        idempotency_key=row.idempotency_key, request_number=f"PR-{request.number:04d}", vendor_ref=vendor.erp_ref,
        po_date=today, schedule_date=request.needed_by or today + timedelta(days=DEFAULT_LEAD_DAYS),
        currency=request.currency,
        lines=[DraftLine(item_code=line.item_code or "", description=line.description, hsn=line.hsn,
                         qty=line.qty, rate=line.est_rate, amount=line.amount) for line in lines])


def order_reference(db: Session, order: OrderPo) -> str:
    """"PO-0001 (PR-0005, PR-0006)": the ERP's remarks name every request the order covers."""
    numbers = db.scalars(select(PurchaseRequest.number).distinct()
                         .join(OrderPoLineSource, OrderPoLineSource.request_id == PurchaseRequest.id)
                         .join(OrderPoLine, OrderPoLine.id == OrderPoLineSource.order_po_line_id)
                         .where(OrderPoLine.order_po_id == order.id).order_by(PurchaseRequest.number)).all()
    return f"PO-{order.number:04d} ({', '.join(f'PR-{n:04d}' for n in numbers)})"


def _build_from_order(db: Session, row: ErpOutbox) -> DraftPo:
    order = db.get(OrderPo, row.order_po_id)
    vendor = db.get(Vendor, order.vendor_id)
    today: date = datetime.now(IST).date()
    lines = db.scalars(select(OrderPoLine).where(OrderPoLine.order_po_id == order.id)
                       .order_by(OrderPoLine.line_no)).all()
    return DraftPo(
        idempotency_key=row.idempotency_key, request_number=order_reference(db, order), vendor_ref=vendor.erp_ref,
        po_date=today, schedule_date=order.needed_by or today + timedelta(days=DEFAULT_LEAD_DAYS),
        currency=order.currency,
        lines=[DraftLine(item_code=line.item_code, description=line.description, hsn=line.hsn, qty=line.qty,
                         rate=line.rate, amount=line.amount, uom=line.unit) for line in lines])


def on_po_confirmed(db: Session, row: ErpOutbox) -> None:
    if row.order_po_id is not None:
        # The Orrfin PO keeps its own status (approved → sent); its page shows the ERP number from the outbox.
        record_event(db, org_id=row.org_id, entity_type="order_po", entity_id=row.order_po_id, actor_id=None,
                     action="erp_draft_confirmed", payload={"erp_doc_name": row.erp_doc_name})
        return
    request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == row.request_id).with_for_update())
    if request.status == "approved":
        request.status = "po_drafted"
        erp = spec_for(db.get(ErpConnection, row.erp_connection_id).system).name
        record_event(db, org_id=request.org_id, entity_type="purchase_request", entity_id=request.id, actor_id=None,
                     action="po_drafted", payload={"status": "po_drafted", "erp_doc_name": row.erp_doc_name, "erp": erp})


def on_po_seen_in_erp(db: Session, request_id: uuid.UUID, po_erp_ref: str) -> None:
    """Called by the pull sync when a *submitted* PO carrying our key arrives: the request's PO is open."""
    request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == request_id).with_for_update())
    if request is not None and request.status in ("approved", "po_drafted"):
        previous = request.status
        request.status = "po_open"
        record_event(db, org_id=request.org_id, entity_type="purchase_request", entity_id=request.id, actor_id=None,
                     action="po_open", payload={"status": "po_open", "from": previous, "po": po_erp_ref})
