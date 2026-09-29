"""ERP pull sync: mirror vendors, POs and receipts into Orrfin (BUILD_PLAN §2, §4).

Rule (§4): upsert by erp_ref; if erp_modified is unchanged, skip the record entirely.
Order matters: vendors first (POs point at them), then POs, then receipts (their lines
point at PO lines). One audit event records each completed pull with its counts.
"""

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT, get_settings
from app.jobs import handler
from app.models import ErpOutbox, GoodsReceipt, GrnLine, Job, PoLine, PurchaseOrder, Vendor
from app.modules.audit.service import record_event
from app.ports.erp import ErpAdapter


def get_erp_adapter() -> ErpAdapter:
    """The fake ERPNext until the live trial starts (Step 11 swaps in the REST adapter here)."""
    return FakeErpnextAdapter(REPO_ROOT / get_settings().erp_fixtures_dir)


def _by_ref(db: Session, model, org_id: uuid.UUID) -> dict[str, Any]:
    return {row.erp_ref: row for row in db.scalars(select(model).where(model.org_id == org_id))}


def _apply(row, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(row, key, value)


def pull_from_erp(db: Session, org_id: uuid.UUID, adapter: ErpAdapter) -> dict[str, dict[str, int]]:
    """Mirror everything the adapter returns. The caller commits. Returns per-type counts."""
    counts: dict[str, Counter] = {k: Counter(created=0, updated=0, unchanged=0)
                                  for k in ("vendors", "purchase_orders", "receipts")}

    vendors = _by_ref(db, Vendor, org_id)
    for record in adapter.list_vendors():
        values = {"name": record.name, "gstin": record.gstin, "state_code": record.state_code,
                  "erp_modified": record.modified}
        row = vendors.get(record.erp_ref)
        if row is None:
            row = Vendor(org_id=org_id, erp_ref=record.erp_ref, **values)
            db.add(row)
            vendors[record.erp_ref] = row
            counts["vendors"]["created"] += 1
        elif row.erp_modified == record.modified:
            counts["vendors"]["unchanged"] += 1
        else:
            _apply(row, values)
            counts["vendors"]["updated"] += 1
    db.flush()

    pos = _by_ref(db, PurchaseOrder, org_id)
    po_lines = _by_ref(db, PoLine, org_id)
    for record in adapter.list_purchase_orders():
        row = pos.get(record.erp_ref)
        if row is not None and row.erp_modified == record.modified:
            counts["purchase_orders"]["unchanged"] += 1
            continue
        vendor = vendors.get(record.vendor_ref)
        # A PO Orrfin drafted carries orrfin_ref = its outbox idempotency key (§8), which links
        # it back to the purchase request.
        request_id = None
        if record.orrfin_ref:
            request_id = db.scalar(select(ErpOutbox.request_id).where(
                ErpOutbox.org_id == org_id, ErpOutbox.idempotency_key == record.orrfin_ref))
        values = {
            "erp_modified": record.modified, "vendor_id": vendor.id if vendor else None,
            "po_date": record.po_date, "schedule_date": record.schedule_date, "status": record.status,
            "currency": record.currency, "net_total": record.net_total, "tax_total": record.tax_total,
            "grand_total": record.grand_total, "origin": "orrfin" if record.orrfin_ref else "erp",
            "request_id": request_id,
        }
        if row is None:
            row = PurchaseOrder(org_id=org_id, erp_ref=record.erp_ref, **values)
            db.add(row)
            db.flush()
            pos[record.erp_ref] = row
            counts["purchase_orders"]["created"] += 1
        else:
            _apply(row, values)
            counts["purchase_orders"]["updated"] += 1
        for line in record.lines:
            line_values = {"po_id": row.id, "line_no": line.line_no, "item_code": line.item_code,
                           "description": line.description, "hsn": line.hsn, "uom": line.uom,
                           "qty": line.qty, "rate": line.rate, "amount": line.amount,
                           "tax_rate": line.tax_rate}
            existing = po_lines.get(line.erp_ref)
            if existing is None:
                existing = PoLine(org_id=org_id, erp_ref=line.erp_ref, **line_values)
                db.add(existing)
                po_lines[line.erp_ref] = existing
            else:
                _apply(existing, line_values)
    db.flush()

    receipts = _by_ref(db, GoodsReceipt, org_id)
    grn_lines = _by_ref(db, GrnLine, org_id)
    for record in adapter.list_receipts():
        row = receipts.get(record.erp_ref)
        if row is not None and row.erp_modified == record.modified:
            counts["receipts"]["unchanged"] += 1
            continue
        vendor = vendors.get(record.vendor_ref)
        values = {"erp_modified": record.modified, "vendor_id": vendor.id if vendor else None,
                  "posting_date": record.posting_date, "status": record.status}
        if row is None:
            row = GoodsReceipt(org_id=org_id, erp_ref=record.erp_ref, **values)
            db.add(row)
            db.flush()
            receipts[record.erp_ref] = row
            counts["receipts"]["created"] += 1
        else:
            _apply(row, values)
            counts["receipts"]["updated"] += 1
        for line in record.lines:
            po_line = po_lines.get(line.po_line_ref or "")
            line_values = {"receipt_id": row.id, "item_code": line.item_code,
                           "qty_received": line.qty_received, "po_line_id": po_line.id if po_line else None}
            existing = grn_lines.get(line.erp_ref)
            if existing is None:
                db.add(GrnLine(org_id=org_id, erp_ref=line.erp_ref, **line_values))
            else:
                _apply(existing, line_values)
    db.flush()
    return {kind: dict(c) for kind, c in counts.items()}


@handler("erp_pull")
def run_erp_pull(db: Session, job: Job) -> dict[str, Any]:
    result = pull_from_erp(db, job.org_id, get_erp_adapter())
    record_event(db, org_id=job.org_id, entity_type="erp_sync", entity_id=job.id,
                 actor_id=job.created_by, action="erp_pull_completed", payload=result)
    return result
