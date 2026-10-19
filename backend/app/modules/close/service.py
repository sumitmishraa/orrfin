"""Month-end close cockpit (BUILD_PLAN v2.4 change 32; ADR 0008; PROMPTS Step 26).

DualEntry runs the close inside the ledger. Orrfin keeps no ledger, so its close is a cockpit over the
procure-to-pay side: a live checklist, a received-not-invoiced report (an accrual *report*, never a
journal), AI "what changed" notes, and a named sign-off. A closed month refuses invoice approvals dated
in it, and payment approvals while it is the current month, until an admin reopens it with a reason.
"""

import csv
import io
import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid
from app.models import (
    ClosePeriod,
    ErpOutbox,
    ExceptionTask,
    GoodsReceipt,
    GrnLine,
    Invoice,
    InvoiceLine,
    PaymentLine,
    PoLine,
    PurchaseOrder,
    User,
    Vendor,
)
from app.modules.audit.service import record_event
from app.modules.bank.service import reconciled_payment_ids

IST = ZoneInfo("Asia/Kolkata")
CLOSERS = ("finance", "admin")
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ZERO = Decimal("0")
# Later steps add checks here without this module importing them: fn(db, org_id, first, last) -> dict | None.
EXTRA_CHECKS: list = []


def period_of(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def bounds(period: str) -> tuple[date, date]:
    """First day of the month and first day of the next month."""
    if not _PERIOD.match(period or ""):
        raise Invalid('A period looks like "2026-10".')
    year, month = int(period[:4]), int(period[5:])
    return date(year, month, 1), date(year + month // 12, month % 12 + 1, 1)


def _utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=IST).astimezone(UTC)


def checklist(db: Session, org_id: uuid.UUID, period: str) -> list[dict[str, Any]]:
    first, after = bounds(period)
    items = []
    undecided = list(db.scalars(select(Invoice).where(
        Invoice.org_id == org_id, Invoice.invoice_date >= first, Invoice.invoice_date < after,
        Invoice.status.notin_(("approved", "rejected")))))
    items.append({"key": "invoices_decided", "label": "Every invoice dated in the month is approved or rejected",
                  "open": len(undecided), "items": [f"{i.invoice_no or i.id} ({i.status})" for i in undecided[:10]]})
    questions = db.scalar(select(func.count()).select_from(ExceptionTask).join(Invoice, Invoice.id == ExceptionTask.invoice_id)
                          .where(ExceptionTask.org_id == org_id, ExceptionTask.status != "closed",
                                 Invoice.invoice_date >= first, Invoice.invoice_date < after))
    items.append({"key": "questions_closed", "label": "No open questions on the month's invoices",
                  "open": questions, "items": []})
    reconciled = reconciled_payment_ids(db, org_id)
    paid = [p for p in db.scalars(select(PaymentLine).where(
        PaymentLine.org_id == org_id, PaymentLine.status == "paid",
        PaymentLine.paid_at >= _utc(first), PaymentLine.paid_at < _utc(after))) if p.id not in reconciled]
    items.append({"key": "payments_reconciled", "label": "Every payment made in the month is matched to the bank statement",
                  "open": len(paid), "items": [p.utr or str(p.id) for p in paid[:10]]})
    failed = db.scalar(select(func.count()).select_from(ErpOutbox).where(
        ErpOutbox.org_id == org_id, ErpOutbox.state.in_(("FAILED", "UNKNOWN"))))
    items.append({"key": "erp_syncs_ok", "label": "No draft PO or bill failed or stuck on its way to the ERP",
                  "open": failed, "items": []})
    for check in EXTRA_CHECKS:
        item = check(db, org_id, first, after)
        if item is not None:
            items.append(item)
    for item in items:
        item["ok"] = item["open"] == 0
    return items


def received_not_invoiced(db: Session, org_id: uuid.UUID, period: str) -> list[dict[str, Any]]:
    """Goods and services received in the month and not yet billed on an approved invoice, at the PO rate.
    A report for the accountant's accrual; Orrfin posts nothing."""
    first, after = bounds(period)
    received_in_month: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    received_to_date: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for line, receipt in db.execute(select(GrnLine, GoodsReceipt).join(GoodsReceipt, GoodsReceipt.id == GrnLine.receipt_id)
                                    .where(GrnLine.org_id == org_id, GrnLine.po_line_id.is_not(None),
                                           GoodsReceipt.posting_date < after)).all():
        received_to_date[line.po_line_id] += line.qty_received
        if receipt.posting_date and receipt.posting_date >= first:
            received_in_month[line.po_line_id] += line.qty_received
    if not received_in_month:
        return []
    invoiced = dict(db.execute(select(InvoiceLine.po_line_id, func.sum(InvoiceLine.qty))
                               .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                               .where(Invoice.org_id == org_id, Invoice.status == "approved",
                                      InvoiceLine.po_line_id.in_(list(received_in_month)))
                               .group_by(InvoiceLine.po_line_id)).all())
    rows = []
    for po_line_id, in_month in received_in_month.items():
        open_qty = min(in_month, max(ZERO, received_to_date[po_line_id] - (invoiced.get(po_line_id) or ZERO)))
        if open_qty <= 0:
            continue
        line, po = db.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                              .where(PoLine.id == po_line_id)).one()
        vendor = db.get(Vendor, po.vendor_id) if po.vendor_id else None
        rows.append({"vendor": vendor.name if vendor else "Unknown", "po": po.po_number or po.erp_ref,
                     "item_code": line.item_code, "qty": open_qty, "rate": line.rate,
                     "amount": (open_qty * line.rate).quantize(Decimal("0.01"))})
    return sorted(rows, key=lambda r: (r["vendor"], r["po"], r["item_code"]))


def received_not_invoiced_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Vendor", "PO", "Item code", "Qty received, not invoiced", "PO rate", "Amount"])
    for r in rows:
        writer.writerow([r["vendor"], r["po"], r["item_code"], f"{r['qty']}", f"{r['rate']:.2f}", f"{r['amount']:.2f}"])
    return out.getvalue()


def _period_row(db: Session, org_id: uuid.UUID, period: str, *, lock: bool = False) -> ClosePeriod | None:
    query = select(ClosePeriod).where(ClosePeriod.org_id == org_id, ClosePeriod.period == period)
    return db.scalar(query.with_for_update() if lock else query)


def close(db: Session, user: User, period: str, notes: dict[str, str]) -> ClosePeriod:
    if user.role not in CLOSERS:
        raise Forbidden("Only finance or an admin can close a month.")
    first, _ = bounds(period)
    if first > datetime.now(IST).date():
        raise Invalid("A month that has not started cannot be closed.")
    row = _period_row(db, user.org_id, period, lock=True)
    if row is not None and row.status == "closed":
        raise Conflict(f"{period} is already closed.")
    items = checklist(db, user.org_id, period)
    unexplained = [i["label"] for i in items if not i["ok"] and not (notes.get(i["key"]) or "").strip()]
    if unexplained:
        raise Invalid("Explain each open item before closing: " + "; ".join(unexplained))
    if row is None:
        row = ClosePeriod(org_id=user.org_id, period=period)
        db.add(row)
        db.flush()
    row.status, row.closed_by, row.closed_at = "closed", user.id, datetime.now(UTC)
    row.close_notes = {"checklist": [{k: i[k] for k in ("key", "label", "open", "ok")} for i in items],
                       "notes": {k: v.strip() for k, v in notes.items() if v and v.strip()}}
    record_event(db, org_id=user.org_id, entity_type="close_period", entity_id=row.id, actor_id=user.id,
                 action="month_closed", payload={"period": period, **row.close_notes})
    return row


def reopen(db: Session, user: User, period: str, reason: str) -> ClosePeriod:
    if user.role != "admin":
        raise Forbidden("Only an admin can reopen a closed month.")
    row = _period_row(db, user.org_id, period, lock=True)
    if row is None or row.status != "closed":
        raise Conflict(f"{period} is not closed.")
    if not (reason or "").strip():
        raise Invalid("Give a reason to reopen the month.")
    row.status, row.reopened_by, row.reopen_reason = "open", user.id, reason.strip()
    record_event(db, org_id=user.org_id, entity_type="close_period", entity_id=row.id, actor_id=user.id,
                 action="month_reopened", payload={"period": period, "reason": reason.strip()})
    return row


def locked_refusal(db: Session, org_id: uuid.UUID, day: date | None, what: str) -> Conflict | None:
    """Refuse an approval dated in a closed month (called by invoice and payment approval)."""
    if day is None:
        return None
    row = _period_row(db, org_id, period_of(day))
    if row is not None and row.status == "closed":
        return Conflict(f"{period_of(day)} is closed, so {what} dated in it cannot be approved. "
                        "An admin can reopen the month with a reason.")
    return None


def view(db: Session, user: User, period: str) -> dict[str, Any]:
    if user.role not in CLOSERS:
        raise Forbidden("Only finance or an admin can see the close.")
    row = _period_row(db, user.org_id, period)
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    rni = received_not_invoiced(db, user.org_id, period)
    status = row.status if row else "open"
    return {"period": period, "status": status, "checklist": checklist(db, user.org_id, period),
            "closed_by": names.get(row.closed_by) if row else None, "closed_at": row.closed_at if row else None,
            "close_notes": row.close_notes if row else {}, "reopen_reason": row.reopen_reason if row else None,
            "received_not_invoiced": rni, "received_not_invoiced_total": sum((r["amount"] for r in rni), ZERO),
            "can_close": status == "open", "can_reopen": status == "closed" and user.role == "admin"}


def current_period() -> str:
    return period_of(datetime.now(IST).date())
