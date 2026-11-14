"""PDFs of Orrfin records: purchase order, RFQ and an audit pack (BUILD_PLAN change 49).

Each route loads the record through the same org-scoped, role-checked function the record's own page
uses, so a PDF can never show more than the page would.
"""

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, DbSession
from app.errors import Forbidden, NotFound
from app.models import AuditEvent, PoLine, PurchaseOrder, User, Vendor
from app.modules.audit.service import verify_chain
from app.modules.documents.pdf import build
from app.modules.sourcing import service as sourcing

router = APIRouter(prefix="/documents", tags=["documents"])
VIEW_ROLES = ("buyer", "approver", "finance", "admin")


def _pdf(name: str, data: bytes) -> Response:
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/po/{po_id}")
def purchase_order(po_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    if user.role not in VIEW_ROLES:
        raise Forbidden("Your role cannot see purchase orders.")
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.org_id == user.org_id))
    if po is None:
        raise NotFound("Purchase order not found.")
    vendor = db.get(Vendor, po.vendor_id) if po.vendor_id else None
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no))
    rows = [[str(l.line_no), l.item_code, l.description, f"{l.qty.normalize():f}", f"{l.rate:,.2f}", f"{l.amount:,.2f}"]
            for l in lines]
    return _pdf(f"PO-{po.erp_ref}.pdf", build(
        f"Purchase order {po.po_number or po.erp_ref}", "Copy of the order held in your ERP",
        [("Vendor", vendor.name if vendor else "–"), ("Tax number", (vendor.gstin or "–") if vendor else "–"),
         ("Order date", str(po.po_date or "–")), ("Status in the ERP", po.status), ("Currency", po.currency),
         ("Net", f"{po.net_total:,.2f}"), ("Tax", f"{po.tax_total:,.2f}"), ("Total", f"{po.grand_total:,.2f}")],
        ["#", "Item", "Description", "Qty", "Rate", "Amount"], rows,
        notice="Reference copy from Orrfin's mirror of the ERP. The ERP's own document is the original.",
        source={"po": str(po.id), "erp_modified": po.erp_modified.isoformat(), "rows": rows}))


@router.get("/rfq/{rfq_id}")
def rfq(rfq_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    record = sourcing.load_rfq(db, user, rfq_id)
    detail = sourcing.detail(db, user, record)
    rows = [[str(l["line_no"]), l["description"], f"{l['qty'].normalize():f}", l["uom"]] for l in detail["lines"]]
    facts = [("Status", detail["status"]), ("Currency", detail["currency"]), ("Quotes close", str(detail["closes_at"])),
             ("Scoring", ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in detail["weights"].items()))]
    if detail["comparison"]:
        facts += [(f"Quote: {r['supplier_name']}", f"landed {r['landed_cost'] or '–'}, score {r['score'] or 'not scored'}")
                  for r in detail["comparison"]]
    return _pdf(f"{detail['number']}.pdf", build(
        f"{detail['number']}: {detail['title']}", "Request for quotation", facts, ["#", "Item", "Qty", "Unit"], rows,
        notice="Quotes are sealed until the RFQ closes; the scoring weights were fixed when it opened.",
        source={"rfq": str(record.id), "facts": facts, "rows": rows}))


@router.get("/audit/{entity_id}")
def audit_pack(entity_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Every event of one record, with the hash-chain check. Finance and admins (auditors' contacts) only."""
    if user.role not in ("finance", "admin"):
        raise Forbidden("Only finance or an admin can export an audit pack.")
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.org_id == user.org_id, AuditEvent.entity_id == entity_id)
                             .order_by(AuditEvent.seq)))
    if not events:
        raise NotFound("No history for that record.")
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    intact = verify_chain(db, entity_id)
    rows = [[str(e.seq), e.created_at.strftime("%Y-%m-%d %H:%M"), e.action, names.get(e.actor_id, "System"),
             ", ".join(f"{k}={v}" for k, v in sorted((e.payload or {}).items()))[:300]] for e in events]
    return _pdf(f"audit-{entity_id}.pdf", build(
        f"Audit pack: {events[0].entity_type.replace('_', ' ')}", str(entity_id),
        [("Events", str(len(events))), ("Hash chain", "intact" if intact else "BROKEN: investigate before relying on it")],
        ["#", "When (UTC)", "What", "Who", "Details"], rows,
        notice="Taken from Orrfin's append-only, hash-chained audit trail.", source={"entity": str(entity_id), "rows": rows}))
