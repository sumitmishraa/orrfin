"""Draft purchase orders through the outbox (BUILD_PLAN §8 "Draft Purchase Orders"; PROMPTS Step 15).

Same outbox, states and lookup-before-retry as bills (service.py); only the key and the payload differ:
- key   = sha256(org_id|request_id|"purchase_order"): one PO per approved request;
- push  = the ERP's draft PO (ERPNext: Purchase Order, docstatus 0) carrying the key in its Orrfin Ref field;
- lookup = find_po(key).
CONFIRMED → request `po_drafted`. A person submits the PO inside the ERP; the next pull sync sees it,
linked by the key (origin = orrfin), and the request becomes `po_open` (modules/sync).
"""

import hashlib
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter, spec_for
from app.erp_demo.canonical import IST
from app.jobs import enqueue
from app.models import ErpConnection, ErpOutbox, PurchaseRequest, RequestLine, Vendor
from app.modules.audit.service import record_event
from app.ports.erp import DraftLine, DraftPo

DEFAULT_LEAD_DAYS = 14  # schedule date when the request has no "needed by"


def po_key(request: PurchaseRequest) -> str:
    return hashlib.sha256(f"{request.org_id}|{request.id}|purchase_order".encode("utf-8")).hexdigest()


def po_unavailable_reason(db: Session, request: PurchaseRequest) -> str | None:
    """Why this approved request can't be drafted as a PO in the ERP, or None. Shown on the request page."""
    from app.modules.erp_outbox.service import CONFIG_FAILURES

    vendor = db.get(Vendor, request.vendor_id) if request.vendor_id else None
    if vendor is None:
        return "No ERP vendor was chosen for this request, so there is nobody to order from."
    connection = db.get(ErpConnection, vendor.erp_connection_id)
    name = spec_for(connection.system).name
    if not connection.is_active:
        return (f"The vendor comes from {name} ({connection.mode}), which is no longer the active ERP. "
                "Ask the buyer to pick the vendor again from the active ERP.")
    try:
        caps = get_adapter(connection).capabilities()
    except CONFIG_FAILURES as exc:
        return f"{name} isn't ready: {exc}"
    if not caps.can_write_po:
        return caps.write_note or f"{name} can't hold draft purchase orders from Orrfin."
    return None


def queue_po(db: Session, request: PurchaseRequest, actor_id: uuid.UUID) -> ErpOutbox | None:
    """Called in the same transaction as the final approval (§8 "Trigger")."""
    from app.modules.erp_outbox.service import _audit, _erp_name

    if po_unavailable_reason(db, request):
        return None
    key = po_key(request)
    existing = db.scalar(select(ErpOutbox).where(ErpOutbox.idempotency_key == key))
    if existing is not None:
        return existing
    vendor = db.get(Vendor, request.vendor_id)
    row = ErpOutbox(org_id=request.org_id, erp_connection_id=vendor.erp_connection_id, idempotency_key=key,
                    doc_type="purchase_order", request_id=request.id, state="PENDING")
    db.add(row)
    db.flush()
    enqueue(db, org_id=request.org_id, kind="erp_push", payload={"outbox_id": str(row.id)}, created_by=actor_id)
    _audit(db, row, actor_id, "erp_draft_queued", {"request_id": request.id, "erp": _erp_name(db, row)})
    return row


def build_draft_po(db: Session, row: ErpOutbox) -> DraftPo:
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


def on_po_confirmed(db: Session, row: ErpOutbox) -> None:
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
