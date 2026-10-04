"""Checks run on invoice fields after extraction or editing (BUILD_PLAN §7 "Validation after the model returns").

Pure functions: no database, no AI. Any issue blocks automatic matching and highlights the
field for the finance user; they fix it, or confirm "as printed" when the document itself is
wrong (e.g. a vendor's mistyped GSTIN), and the matching rules then raise the exception.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# BUILD_PLAN §6 rule 7. The check character is not verified here: advisory only until checked
# against an official GSTN source.
GSTIN_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
DATE_WINDOW = timedelta(days=400)
# §6 rule 4: invoice-level arithmetic tolerance (₹1.00), reported as round-off.
ARITHMETIC_TOLERANCE = Decimal("1.00")
MONEY_FIELDS = ("subtotal", "cgst", "sgst", "igst", "total")


@dataclass
class LineFields:
    description: str | None
    item_code: str | None
    hsn: str | None
    qty: str | None
    rate: str | None
    amount: str | None


@dataclass
class InvoiceFields:
    vendor_gstin: str | None
    buyer_gstin: str | None
    invoice_no: str | None
    invoice_date: str | None
    po_reference: str | None
    lines: list[LineFields] = field(default_factory=list)
    subtotal: str | None = None
    cgst: str | None = None
    sgst: str | None = None
    igst: str | None = None
    total: str | None = None


@dataclass
class Issue:
    field: str
    code: str
    message: str


def parse_money(value: str | None) -> Decimal | None:
    """A plain decimal string → Decimal. Commas, symbols or text → None (flagged, never guessed)."""
    if value is None or not re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def parse_date(value: str | None) -> date | None:
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def normalize_invoice_no(value: str) -> str:
    """BUILD_PLAN §5 duplicate key: upper-case, drop spaces and / - _, strip leading zeros."""
    return re.sub(r"[\s/\-_]", "", value.upper()).lstrip("0")


def fiscal_year(day: date) -> str:
    """Indian financial year, April to March: 10 Sep 2026 → "2026-27"."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def validate(fields: InvoiceFields, today: date) -> list[Issue]:
    issues: list[Issue] = []

    def flag(name: str, code: str, message: str) -> None:
        issues.append(Issue(name, code, message))

    for name in ("invoice_no", "po_reference", "vendor_gstin", "invoice_date"):
        if not (getattr(fields, name) or "").strip():
            flag(name, "REQUIRED", "This field is required.")

    gstin = (fields.vendor_gstin or "").strip()
    if gstin and not GSTIN_FORMAT.match(gstin):
        flag("vendor_gstin", "GSTIN_FORMAT", f"“{gstin}” is not a valid GSTIN format.")
    elif not gstin:
        flag("vendor_gstin", "GSTIN_FORMAT", "The vendor GSTIN is missing.")
    buyer = (fields.buyer_gstin or "").strip()
    if buyer and not GSTIN_FORMAT.match(buyer):
        flag("buyer_gstin", "GSTIN_FORMAT", f"“{buyer}” is not a valid GSTIN format.")

    if fields.invoice_date:
        day = parse_date(fields.invoice_date)
        if day is None:
            flag("invoice_date", "DATE_INVALID", "Use a real date in the form YYYY-MM-DD.")
        elif abs(day - today) > DATE_WINDOW:
            flag("invoice_date", "DATE_OUT_OF_RANGE", "The date is more than 400 days from today.")

    money = {name: parse_money(getattr(fields, name)) for name in MONEY_FIELDS}
    for name, value in money.items():
        if value is None:
            flag(name, "NOT_A_NUMBER", "Enter a plain number, e.g. 54870.00.")

    if not fields.lines:
        flag("lines", "REQUIRED", "An invoice needs at least one line.")
    line_amounts: list[Decimal] = []
    for n, line in enumerate(fields.lines, start=1):
        qty, rate, amount = parse_money(line.qty), parse_money(line.rate), parse_money(line.amount)
        for attr, value in (("qty", qty), ("rate", rate), ("amount", amount)):
            if value is None:
                flag(f"lines[{n}].{attr}", "NOT_A_NUMBER", "Enter a plain number.")
        if qty is not None and rate is not None and amount is not None:
            line_amounts.append(amount)
            if abs(qty * rate - amount) > ARITHMETIC_TOLERANCE:
                flag(f"lines[{n}].amount", "LINE_ARITHMETIC",
                     f"{line.qty} × {line.rate} = {qty * rate:.2f}, but the line says {line.amount}.")

    if None not in money.values():
        if len(line_amounts) == len(fields.lines) and fields.lines:
            if abs(sum(line_amounts) - money["subtotal"]) > ARITHMETIC_TOLERANCE:
                flag("subtotal", "SUBTOTAL_MISMATCH",
                     f"The lines add up to {sum(line_amounts):.2f}, not {fields.subtotal}.")
        expected_total = money["subtotal"] + money["cgst"] + money["sgst"] + money["igst"]
        if abs(expected_total - money["total"]) > ARITHMETIC_TOLERANCE:
            flag("total", "TOTAL_MISMATCH", f"Subtotal plus taxes is {expected_total:.2f}, not {fields.total}.")
        if abs(money["cgst"] - money["sgst"]) > ARITHMETIC_TOLERANCE:
            flag("cgst", "CGST_SGST_UNEQUAL", "CGST and SGST are each half of the GST, so they must be equal.")
    return issues
