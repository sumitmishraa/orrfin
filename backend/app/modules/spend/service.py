"""The spend cube (BUILD_PLAN change 49). Deterministic: every number is a sum of stored records, no AI.

Three measures are kept apart because they mean different things and are never interchangeable:
- committed: purchase orders mirrored from the ERP (what the company promised to pay);
- invoiced: invoices that matched or were approved (what suppliers asked for and passed the gate);
- paid: simulated payment lines the mock bank paid (net of TDS).
Every row is per currency: amounts in different currencies are never added together.
"""

import csv
import io
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Forbidden, Invalid
from app.models import (
    Category, Contract, Invoice, LegalEntity, PaymentLine, PaymentRun, PurchaseOrder, PurchaseRequest, RfqAward, Vendor,
)

VIEW_ROLES = ("buyer", "approver", "finance", "admin")
DIMENSIONS = ("vendor", "category", "cost_center", "month", "entity")
INVOICED_STATUSES = ("matched", "approved")
ZERO = Decimal("0.00")


def _period_ok(day: date | None, start: date | None, end: date | None) -> bool:
    return day is not None and (start is None or day >= start) and (end is None or day <= end)


def cube(db: Session, user, group_by: str, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    if user.role not in VIEW_ROLES:
        raise Forbidden("Your role cannot see spend.")
    if group_by not in DIMENSIONS:
        raise Invalid(f"Group by one of: {', '.join(DIMENSIONS)}.")
    org = user.org_id
    vendors = dict(db.execute(select(Vendor.id, Vendor.name).where(Vendor.org_id == org)).all())
    categories = dict(db.execute(select(Category.id, Category.name).where(Category.org_id == org)).all())
    entities = dict(db.execute(select(LegalEntity.id, LegalEntity.name).where(LegalEntity.org_id == org)).all())
    requests = {r.id: r for r in db.scalars(select(PurchaseRequest).where(PurchaseRequest.org_id == org))}
    pos = {p.id: p for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.org_id == org))}

    def key(vendor_id, request_id, day: date | None, entity_id=None) -> str:
        request = requests.get(request_id) if request_id else None
        if group_by == "vendor":
            return vendors.get(vendor_id, "No vendor")
        if group_by == "category":
            return categories.get(request.category_id, "No request") if request else "No request"
        if group_by == "cost_center":
            return (request.cost_center or "None") if request else "No request"
        if group_by == "entity":
            return entities.get(entity_id, "Default entity")
        return day.strftime("%Y-%m") if day else "No date"

    rows: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: {"committed": ZERO, "invoiced": ZERO, "paid": ZERO})
    for po in pos.values():
        if _period_ok(po.po_date, start, end):
            rows[(key(po.vendor_id, po.request_id, po.po_date), po.currency)]["committed"] += po.grand_total
    invoices = list(db.scalars(select(Invoice).where(Invoice.org_id == org, Invoice.status.in_(INVOICED_STATUSES))))
    for inv in invoices:
        if _period_ok(inv.invoice_date, start, end):
            po = pos.get(inv.po_id)
            rows[(key(inv.vendor_id, po.request_id if po else None, inv.invoice_date, inv.entity_id), inv.currency)]["invoiced"] += inv.total or ZERO
    paid = db.execute(select(PaymentLine, PaymentRun.currency).join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
                      .where(PaymentLine.org_id == org, PaymentLine.status == "paid")).all()
    by_invoice = {i.id: i for i in invoices}
    for line, currency in paid:
        day = line.paid_at.date() if line.paid_at else None
        if _period_ok(day, start, end):
            inv = by_invoice.get(line.invoice_id) or db.get(Invoice, line.invoice_id)
            po = pos.get(inv.po_id) if inv else None
            rows[(key(line.vendor_id, po.request_id if po else None, day, inv.entity_id if inv else None), currency)]["paid"] += line.net

    # No-PO spend: invoices that passed without a purchase order. Off-contract: vendors with no active contract.
    contracted = set(db.scalars(select(Contract.vendor_id).where(Contract.org_id == org, Contract.status == "active",
                                                                 Contract.vendor_id.is_not(None))))
    no_po: dict[str, Decimal] = defaultdict(lambda: ZERO)
    off_contract: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for inv in invoices:
        if _period_ok(inv.invoice_date, start, end):
            if inv.po_id is None:
                no_po[inv.currency] += inv.total or ZERO
            if inv.vendor_id not in contracted:
                off_contract[inv.currency] += inv.total or ZERO
    return {
        "group_by": group_by, "from": start, "to": end,
        "rows": [{"group": g, "currency": c, **m} for (g, c), m in sorted(rows.items())],
        "no_po_spend": dict(no_po), "off_contract_spend": dict(off_contract),
        "sourcing_savings": savings(db, org),
        "notes": ["Committed = ERP purchase orders; invoiced = matched or approved invoices; paid = simulated payments. "
                  "Currencies are never added together."],
    }


def savings(db: Session, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per awarded RFQ: the average of the other scored quotes minus the awarded one, with the arithmetic."""
    out = []
    for award in db.scalars(select(RfqAward).where(RfqAward.org_id == org_id)):
        rows = [r for r in award.comparison_snapshot.get("rows", []) if r.get("landed_cost") is not None]
        chosen = next((r for r in rows if r["quote_id"] == str(award.quote_id)), None)
        others = [Decimal(str(r["landed_cost"])) for r in rows if r is not chosen]
        if chosen is None or not others:
            continue
        average = (sum(others) / len(others)).quantize(Decimal("0.01"))
        saved = average - Decimal(str(chosen["landed_cost"]))
        out.append({"rfq_id": award.rfq_id, "awarded": chosen["landed_cost"], "average_of_others": average,
                    "saving": saved, "arithmetic": f"{average} − {chosen['landed_cost']} = {saved}"})
    return out


def as_csv(data: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([data["group_by"], "Currency", "Committed", "Invoiced", "Paid"])
    for row in data["rows"]:
        # A leading =, +, - or @ would run as a formula in a spreadsheet; prefix it so it stays text.
        group = str(row["group"])
        writer.writerow(["'" + group if group[:1] in "=+-@" else group, row["currency"],
                         f"{row['committed']:.2f}", f"{row['invoiced']:.2f}", f"{row['paid']:.2f}"])
    return out.getvalue()
