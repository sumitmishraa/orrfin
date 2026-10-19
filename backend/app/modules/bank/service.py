"""Bank statement import and reconciliation (BUILD_PLAN v2.4 change 32; ADR 0008; PROMPTS Step 26).

DualEntry matches bank lines with AI; here rules do it (reconcile.py) and a person confirms anything that
is not certain. A statement CSV (the mock bank's, or any with Date, Narration, Reference, Debit, Credit
columns) is imported once; every match, acceptance and undo is audited.
"""

import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import BankLine, BankStatement, PaymentLine, PaymentRun, User, Vendor
from app.modules.audit.service import record_event
from app.modules.bank.reconcile import BankIn, PaymentIn, reconcile

ROLES = ("finance", "admin")
MAX_BYTES = 2 * 1024 * 1024
MAX_LINES = 5000
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y")


def _require(user: User) -> None:
    if user.role not in ROLES:
        raise Forbidden("Only finance or an admin can work with bank statements.")


def _date(text: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise Invalid(f"Unreadable date: {text!r}. Use YYYY-MM-DD.")


def _money(text: str) -> Decimal:
    text = (text or "").replace(",", "").strip()
    if not text:
        return Decimal("0")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise Invalid(f"Unreadable amount: {text!r}.") from None
    if value < 0:
        raise Invalid("Amounts must be positive; use the Debit or Credit column.")
    return value.quantize(Decimal("0.01"))


def parse_statement(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("The statement must be a UTF-8 CSV file.") from None
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    missing = [h for h in ("date", "narration", "debit") if h not in headers]
    if missing:
        raise Invalid(f"The CSV needs these columns: Date, Narration, Reference, Debit, Credit (missing: {', '.join(missing)}).")
    rows = []
    for n, row in enumerate(reader, start=1):
        if n > MAX_LINES:
            raise Invalid(f"At most {MAX_LINES} lines per statement.")
        get = lambda key: (row.get(headers.get(key, ""), "") or "").strip()  # noqa: E731
        if not any(get(k) for k in ("date", "narration", "debit", "credit")):
            continue
        rows.append({"line_no": n, "txn_date": _date(get("date")), "narration": get("narration")[:1000],
                     "reference": get("reference")[:64], "debit": _money(get("debit")), "credit": _money(get("credit"))})
    if not rows:
        raise Invalid("The statement has no lines.")
    return rows


def _paid_lines(db: Session, org_id: uuid.UUID) -> list[PaymentLine]:
    return list(db.scalars(select(PaymentLine).join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
                           .where(PaymentLine.org_id == org_id, PaymentLine.status == "paid")))


def auto_reconcile(db: Session, user: User | None, org_id: uuid.UUID) -> dict[str, int]:
    """Run the rules over every unmatched bank line against every paid, not yet reconciled payment."""
    taken = set(db.scalars(select(BankLine.payment_line_id).where(BankLine.org_id == org_id,
                                                                  BankLine.status == "matched")))
    payments = [p for p in _paid_lines(db, org_id) if p.id not in taken]
    vendors = dict(db.execute(select(Vendor.id, Vendor.name).where(Vendor.org_id == org_id)).all())
    lines = list(db.scalars(select(BankLine).where(BankLine.org_id == org_id, BankLine.status != "matched")))
    result = reconcile(
        [BankIn(str(b.id), b.txn_date, b.narration, b.reference, b.debit) for b in lines],
        [PaymentIn(str(p.id), p.utr, p.net, p.paid_at.date() if p.paid_at else date.min, vendors.get(p.vendor_id, ""))
         for p in payments])
    counts = {"matched": 0, "suggested": 0}
    for line in lines:
        hit = result.get(str(line.id))
        if hit is None:
            line.status, line.payment_line_id, line.match_method = "unmatched", None, None
            continue
        payment_id, status, method = hit
        line.status, line.payment_line_id, line.match_method = status, uuid.UUID(payment_id), method
        if status == "matched":
            line.matched_at, line.matched_by = datetime.now(UTC), None  # matched by rule, not a person
        counts[status] += 1
    return counts


def import_statement(db: Session, user: User, filename: str, data: bytes) -> BankStatement:
    _require(user)
    if len(data) > MAX_BYTES:
        raise Invalid("Statement files are limited to 2 MB.")
    sha = hashlib.sha256(data).hexdigest()
    if db.scalar(select(BankStatement.id).where(BankStatement.org_id == user.org_id, BankStatement.sha256 == sha)):
        raise Conflict("This statement file was already imported.")
    rows = parse_statement(data)
    statement = BankStatement(id=uuid.uuid4(), org_id=user.org_id, filename=filename[:255] or "statement.csv",
                              sha256=sha, uploaded_by=user.id, line_count=len(rows))
    db.add(statement)
    db.flush()
    db.add_all([BankLine(org_id=user.org_id, statement_id=statement.id, **row) for row in rows])
    db.flush()
    counts = auto_reconcile(db, user, user.org_id)
    record_event(db, org_id=user.org_id, entity_type="bank_statement", entity_id=statement.id, actor_id=user.id,
                 action="statement_imported", payload={"filename": statement.filename, "sha256": sha,
                                                       "lines": len(rows), **counts})
    return statement


def _line(db: Session, user: User, line_id: uuid.UUID) -> BankLine:
    _require(user)
    line = db.scalar(select(BankLine).where(BankLine.id == line_id, BankLine.org_id == user.org_id).with_for_update())
    if line is None:
        raise NotFound("Bank line not found.")
    return line


def accept(db: Session, user: User, line_id: uuid.UUID) -> BankLine:
    line = _line(db, user, line_id)
    if line.status != "suggested":
        raise Conflict("Only a suggested match can be accepted.")
    if db.scalar(select(BankLine.id).where(BankLine.payment_line_id == line.payment_line_id,
                                           BankLine.status == "matched")):
        raise Conflict("That payment is already reconciled to another bank line.")
    line.status, line.matched_by, line.matched_at = "matched", user.id, datetime.now(UTC)
    record_event(db, org_id=user.org_id, entity_type="bank_statement", entity_id=line.statement_id, actor_id=user.id,
                 action="match_accepted", payload={"bank_line": line.line_no, "payment_line_id": line.payment_line_id})
    return line


def unmatch(db: Session, user: User, line_id: uuid.UUID) -> BankLine:
    line = _line(db, user, line_id)
    if line.status == "unmatched":
        raise Conflict("This bank line is not matched.")
    previous = line.payment_line_id
    line.status, line.payment_line_id, line.match_method, line.matched_by, line.matched_at = "unmatched", None, None, None, None
    record_event(db, org_id=user.org_id, entity_type="bank_statement", entity_id=line.statement_id, actor_id=user.id,
                 action="match_removed", payload={"bank_line": line.line_no, "payment_line_id": previous})
    return line


def view(db: Session, user: User) -> dict[str, Any]:
    _require(user)
    pay_info = {}
    for line, run in db.execute(select(PaymentLine, PaymentRun).join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
                                .where(PaymentLine.org_id == user.org_id)).all():
        pay_info[line.id] = {"run": f"PAY-{run.number:04d}", "run_id": run.id, "net": line.net, "utr": line.utr}
    rows = db.execute(select(BankLine, BankStatement.filename).join(BankStatement, BankStatement.id == BankLine.statement_id)
                      .where(BankLine.org_id == user.org_id).order_by(BankLine.txn_date.desc(), BankLine.line_no)).all()
    lines = [{"id": b.id, "statement": name, "date": b.txn_date, "narration": b.narration, "reference": b.reference,
              "debit": b.debit, "credit": b.credit, "status": b.status, "method": b.match_method,
              "payment": pay_info.get(b.payment_line_id)} for b, name in rows]
    matched = {b["payment"]["utr"] for b in lines if b["status"] == "matched" and b["payment"]}
    unreconciled = [{"run": info["run"], "run_id": info["run_id"], "net": info["net"], "utr": info["utr"]}
                    for pid, info in pay_info.items() if info["utr"] and info["utr"] not in matched]
    return {"lines": lines, "unreconciled_payments": unreconciled,
            "counts": {s: sum(1 for b in lines if b["status"] == s) for s in ("matched", "suggested", "unmatched")}}


def reconciled_payment_ids(db: Session, org_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(select(BankLine.payment_line_id).where(BankLine.org_id == org_id, BankLine.status == "matched")))
