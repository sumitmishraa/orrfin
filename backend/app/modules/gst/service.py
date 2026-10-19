"""GSTR-2B input-tax-credit matching (BUILD_PLAN v2.4 change 34; ADR 0008; PROMPTS Step 27).

Neither Zip nor DualEntry does this for India. GSTR-2B is the auto-drafted statement of what suppliers
reported against the company's GSTIN; credit (ITC) can be claimed only for invoices that appear there.
Orrfin imports the JSON, matches it to its invoices by rules (match.py) and shows the credit at risk.
Matching only: nothing is filed with GSTN.

The router plugs the result into payments (a "not in GSTR-2B" hold), the close checklist (is the month's
2B imported?) and the dashboard, without those modules importing this one.
"""

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid
from app.models import Gstr2bImport, Gstr2bLine, Invoice, User
from app.modules.audit.service import record_event
from app.modules.gst.match import BookIn, TwoBIn, match_2b
from app.modules.invoices.validation import fiscal_year, normalize_invoice_no

ROLES = ("finance", "admin")
MAX_BYTES = 5 * 1024 * 1024
ZERO = Decimal("0")
# Invoices that count as "in the books" for a period: read and confirmed, not rejected.
BOOK_STATUSES = ("confirmed", "matching", "matched", "exception", "approved", "correction_requested")


def _require(user: User) -> None:
    if user.role not in ROLES:
        raise Forbidden("Only finance or an admin can work with GSTR-2B.")


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0")).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise Invalid(f"Unreadable amount in GSTR-2B: {value!r}.") from None


def parse_2b(data: bytes) -> tuple[str, list[dict[str, Any]]]:
    """The GSTN shape: data.rtnprd ("MMYYYY") and data.docdata.b2b[].{ctin, trdnm, inv[].{inum, dt, val, txval,
    igst, cgst, sgst, itcavl}}. Amounts are read as decimals, never floats."""
    try:
        doc = json.loads(data.decode("utf-8-sig"), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError):
        raise Invalid("GSTR-2B must be the JSON file downloaded from the GST portal.") from None
    body = doc.get("data", doc) if isinstance(doc, dict) else {}
    rtnprd = str(body.get("rtnprd", ""))
    if len(rtnprd) != 6 or not rtnprd.isdigit() or not 1 <= int(rtnprd[:2]) <= 12:
        raise Invalid("The file has no valid return period (rtnprd, e.g. 092026).")
    period = f"{rtnprd[2:]}-{rtnprd[:2]}"
    lines = []
    for supplier in (body.get("docdata") or {}).get("b2b") or []:
        for inv in supplier.get("inv") or []:
            try:
                day = datetime.strptime(str(inv["dt"]), "%d-%m-%Y").date()
            except (KeyError, ValueError):
                raise Invalid(f"Unreadable invoice date in GSTR-2B: {inv.get('dt')!r} (expected DD-MM-YYYY).") from None
            lines.append({"supplier_gstin": str(supplier.get("ctin", "")).upper()[:15],
                          "supplier_name": str(supplier.get("trdnm", ""))[:200],
                          "invoice_no": str(inv.get("inum", ""))[:60], "invoice_date": day,
                          "invoice_value": _money(inv.get("val")), "taxable_value": _money(inv.get("txval")),
                          "igst": _money(inv.get("igst")), "cgst": _money(inv.get("cgst")), "sgst": _money(inv.get("sgst")),
                          "itc_available": str(inv.get("itcavl", "Y")).upper() != "N"})
    return period, lines


def _month(period: str) -> tuple[date, date]:
    year, month = int(period[:4]), int(period[5:])
    return date(year, month, 1), date(year + month // 12, month % 12 + 1, 1)


def _books(db: Session, org_id: uuid.UUID, period: str) -> list[Invoice]:
    first, after = _month(period)
    return list(db.scalars(select(Invoice).where(Invoice.org_id == org_id, Invoice.invoice_date >= first,
                                                 Invoice.invoice_date < after, Invoice.status.in_(BOOK_STATUSES))))


def _tax(i: Invoice) -> Decimal:
    return (i.cgst or ZERO) + (i.sgst or ZERO) + (i.igst or ZERO)


def import_2b(db: Session, user: User, filename: str, data: bytes) -> Gstr2bImport:
    _require(user)
    if len(data) > MAX_BYTES:
        raise Invalid("GSTR-2B files are limited to 5 MB.")
    sha = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Gstr2bImport.id).where(Gstr2bImport.org_id == user.org_id, Gstr2bImport.sha256 == sha)):
        raise Conflict("This GSTR-2B file was already imported.")
    period, rows = parse_2b(data)
    imp = Gstr2bImport(id=uuid.uuid4(), org_id=user.org_id, period=period, filename=filename[:255] or "gstr2b.json",
                       sha256=sha, uploaded_by=user.id)
    db.add(imp)
    db.flush()
    lines = [Gstr2bLine(id=uuid.uuid4(), org_id=user.org_id, import_id=imp.id,
                        invoice_no_norm=normalize_invoice_no(r["invoice_no"]), fiscal_year=fiscal_year(r["invoice_date"]),
                        match_status="not_in_books", **r) for r in rows]
    result = match_2b(
        [TwoBIn(str(ln.id), ln.supplier_gstin, ln.invoice_no, ln.invoice_date, ln.invoice_value,
                ln.igst + ln.cgst + ln.sgst) for ln in lines],
        [BookIn(str(i.id), (i.vendor_gstin or "").upper(), i.invoice_no or "", i.invoice_date, i.total or ZERO, _tax(i))
         for i in _books(db, user.org_id, period)])
    for ln in lines:
        status, invoice_id = result.lines[str(ln.id)]
        ln.match_status, ln.invoice_id = status, uuid.UUID(invoice_id) if invoice_id else None
    db.add_all(lines)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="gstr2b_import", entity_id=imp.id, actor_id=user.id,
                 action="gstr2b_imported", payload={"period": period, "sha256": sha, "lines": len(lines),
                                                    "missing_in_2b": len(result.missing_in_2b),
                                                    "itc_at_risk": result.itc_at_risk})
    return imp


def period_view(db: Session, org_id: uuid.UUID, period: str) -> dict[str, Any]:
    """Current state for a period: every 2B line, and every book invoice the 2B does not show."""
    imports = list(db.scalars(select(Gstr2bImport).where(Gstr2bImport.org_id == org_id, Gstr2bImport.period == period)))
    if not imports:
        return {"period": period, "imported": False}
    lines = list(db.scalars(select(Gstr2bLine).where(Gstr2bLine.import_id.in_([i.id for i in imports]))))
    found = {ln.invoice_id for ln in lines if ln.invoice_id}
    missing = [i for i in _books(db, org_id, period) if i.id not in found]
    return {
        "period": period, "imported": True,
        "lines": [{"supplier": ln.supplier_name, "gstin": ln.supplier_gstin, "invoice_no": ln.invoice_no,
                   "invoice_date": ln.invoice_date, "value": ln.invoice_value, "tax": ln.igst + ln.cgst + ln.sgst,
                   "itc_available": ln.itc_available, "status": ln.match_status, "invoice_id": ln.invoice_id}
                  for ln in sorted(lines, key=lambda x: (x.match_status, x.supplier_name))],
        "missing_in_2b": [{"invoice_id": i.id, "invoice_no": i.invoice_no, "vendor": i.vendor_name,
                           "gstin": i.vendor_gstin, "total": i.total, "tax": _tax(i)} for i in missing],
        "itc_at_risk": sum((_tax(i) for i in missing), ZERO),
        "counts": {s: sum(1 for ln in lines if ln.match_status == s) for s in ("matched", "amount_differs", "not_in_books")},
    }


def view(db: Session, user: User, period: str | None) -> dict[str, Any]:
    _require(user)
    periods = sorted(set(db.scalars(select(Gstr2bImport.period).where(Gstr2bImport.org_id == user.org_id))),
                     reverse=True)
    chosen = period or (periods[0] if periods else None)
    return {"periods": periods, "current": period_view(db, user.org_id, chosen) if chosen else None,
            "note": "Matching only: Orrfin files nothing with GSTN."}


# --- Plug-ins for payments, close and the dashboard (registered by router.py) -----------------------------

def missing_from_2b(db: Session, invoice: Invoice) -> bool | None:
    """None when no GSTR-2B is imported for the invoice's month; else whether the invoice is absent from it."""
    if invoice.invoice_date is None:
        return None
    period = f"{invoice.invoice_date.year}-{invoice.invoice_date.month:02d}"
    imports = list(db.scalars(select(Gstr2bImport.id).where(Gstr2bImport.org_id == invoice.org_id,
                                                            Gstr2bImport.period == period)))
    if not imports:
        return None
    return db.scalar(select(Gstr2bLine.id).where(Gstr2bLine.import_id.in_(imports),
                                                 Gstr2bLine.invoice_id == invoice.id).limit(1)) is None


def close_check(db: Session, org_id: uuid.UUID, first: date, after: date) -> dict[str, Any]:
    period = f"{first.year}-{first.month:02d}"
    imported = db.scalar(select(Gstr2bImport.id).where(Gstr2bImport.org_id == org_id,
                                                       Gstr2bImport.period == period).limit(1)) is not None
    return {"key": "gstr2b_imported", "label": "The month's GSTR-2B is imported and matched", "open": 0 if imported else 1,
            "items": [] if imported else ["Download GSTR-2B from the GST portal and import it on the GST page."]}


def dashboard_section(db: Session, scope: Any, start: Any) -> dict[str, Any] | None:
    if scope.role not in ROLES:
        return None
    periods = sorted(set(db.scalars(select(Gstr2bImport.period).where(Gstr2bImport.org_id == scope.org_id))))
    if not periods:
        return None
    views = [period_view(db, scope.org_id, p) for p in periods]
    return {"periods": periods, "itc_at_risk": sum((v["itc_at_risk"] for v in views), ZERO),
            "missing_in_2b": sum(len(v["missing_in_2b"]) for v in views),
            "amount_differs": sum(v["counts"]["amount_differs"] for v in views)}
