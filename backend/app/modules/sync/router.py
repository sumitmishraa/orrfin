"""HTTP routes for the ERP mirror (BUILD_PLAN §2 read-only mirror; PROMPTS Step 4).

"Sync from ERP" queues an erp_pull job for the worker and returns at once; the page
polls GET /jobs/{id}. Vendors and POs are read-only here: ERPNext owns them.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.jobs import enqueue
from app.models import GoodsReceipt, GrnLine, Job, PoLine, PurchaseOrder, User, Vendor

router = APIRouter(tags=["erp mirror"])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    last_error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    erp_ref: str
    name: str
    gstin: str | None
    state_code: str | None
    erp_modified: datetime


class PoSummary(BaseModel):
    id: uuid.UUID
    erp_ref: str
    vendor_name: str | None
    po_date: date | None
    schedule_date: date | None
    status: str
    origin: str
    grand_total: Decimal
    qty_ordered: Decimal
    qty_received: Decimal


class PoLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_code: str
    description: str
    hsn: str | None
    uom: str | None
    qty: Decimal
    qty_received: Decimal
    rate: Decimal
    amount: Decimal
    tax_rate: Decimal


class ReceiptOut(BaseModel):
    erp_ref: str
    posting_date: date | None
    status: str


class PoDetail(PoSummary):
    vendor_gstin: str | None
    currency: str
    net_total: Decimal
    tax_total: Decimal
    erp_modified: datetime
    lines: list[PoLineOut]
    receipts: list[ReceiptOut]


@router.post("/sync/erp", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def start_erp_sync(db: DbSession,
                   user: User = Depends(require_roles("admin", "finance", "buyer"))) -> Job:
    job = enqueue(db, org_id=user.org_id, kind="erp_pull", created_by=user.id)
    db.commit()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.org_id == user.org_id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(user: CurrentUser, db: DbSession) -> list[Vendor]:
    return list(db.scalars(select(Vendor).where(Vendor.org_id == user.org_id).order_by(Vendor.name)))


def _received_by_line(db, org_id: uuid.UUID, po_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(GrnLine.po_line_id, func.sum(GrnLine.qty_received))
        .join(PoLine, PoLine.id == GrnLine.po_line_id)
        .where(GrnLine.org_id == org_id, PoLine.po_id.in_(po_ids))
        .group_by(GrnLine.po_line_id)
    ).all()
    return {line_id: qty for line_id, qty in rows}


@router.get("/purchase-orders", response_model=list[PoSummary])
def list_purchase_orders(user: CurrentUser, db: DbSession) -> list[PoSummary]:
    rows = db.execute(
        select(PurchaseOrder, Vendor.name)
        .outerjoin(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(PurchaseOrder.org_id == user.org_id)
        .order_by(PurchaseOrder.po_date.desc(), PurchaseOrder.erp_ref.desc())
    ).all()
    po_ids = [po.id for po, _ in rows]
    lines = db.scalars(select(PoLine).where(PoLine.po_id.in_(po_ids))).all() if po_ids else []
    received = _received_by_line(db, user.org_id, po_ids) if po_ids else {}
    ordered: dict[uuid.UUID, Decimal] = {}
    got: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        ordered[line.po_id] = ordered.get(line.po_id, Decimal("0")) + line.qty
        got[line.po_id] = got.get(line.po_id, Decimal("0")) + received.get(line.id, Decimal("0"))
    return [
        PoSummary(id=po.id, erp_ref=po.erp_ref, vendor_name=vendor_name, po_date=po.po_date,
                  schedule_date=po.schedule_date, status=po.status, origin=po.origin,
                  grand_total=po.grand_total, qty_ordered=ordered.get(po.id, Decimal("0")),
                  qty_received=got.get(po.id, Decimal("0")))
        for po, vendor_name in rows
    ]


@router.get("/purchase-orders/{po_id}", response_model=PoDetail)
def get_purchase_order(po_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PoDetail:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.org_id == user.org_id))
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase order not found.")
    vendor = db.get(Vendor, po.vendor_id) if po.vendor_id else None
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    received = _received_by_line(db, user.org_id, [po.id])
    receipts = db.scalars(
        select(GoodsReceipt).distinct()
        .join(GrnLine, GrnLine.receipt_id == GoodsReceipt.id)
        .join(PoLine, PoLine.id == GrnLine.po_line_id)
        .where(PoLine.po_id == po.id)
        .order_by(GoodsReceipt.erp_ref)
    ).all()
    line_out = [
        PoLineOut(id=l.id, line_no=l.line_no, item_code=l.item_code, description=l.description,
                  hsn=l.hsn, uom=l.uom, qty=l.qty, qty_received=received.get(l.id, Decimal("0.000")),
                  rate=l.rate, amount=l.amount, tax_rate=l.tax_rate)
        for l in lines
    ]
    return PoDetail(
        id=po.id, erp_ref=po.erp_ref, vendor_name=vendor.name if vendor else None,
        vendor_gstin=vendor.gstin if vendor else None, po_date=po.po_date,
        schedule_date=po.schedule_date, status=po.status, origin=po.origin, currency=po.currency,
        net_total=po.net_total, tax_total=po.tax_total, grand_total=po.grand_total,
        erp_modified=po.erp_modified,
        qty_ordered=sum((l.qty for l in line_out), Decimal("0")),
        qty_received=sum((l.qty_received for l in line_out), Decimal("0")),
        lines=line_out,
        receipts=[ReceiptOut(erp_ref=r.erp_ref, posting_date=r.posting_date, status=r.status) for r in receipts],
    )
