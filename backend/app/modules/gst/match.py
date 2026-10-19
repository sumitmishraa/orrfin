"""GSTR-2B matching rules (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Pure: no database, no AI.

Key: supplier GSTIN + normalised invoice number (the §5 duplicate-key normaliser) + financial year.
- found, invoice value within ₹1.00 → matched;
- found, value differs by more → amount_differs (check with the supplier before claiming credit);
- in GSTR-2B, not in the books → not_in_books;
- in the books, not in GSTR-2B → missing_in_2b: the supplier has not reported it, so the credit (the
  invoice's GST) is at risk.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.modules.invoices.validation import fiscal_year, normalize_invoice_no

TOLERANCE = Decimal("1.00")


@dataclass(frozen=True)
class TwoBIn:
    id: str
    gstin: str
    invoice_no: str
    invoice_date: date
    value: Decimal
    tax: Decimal


@dataclass(frozen=True)
class BookIn:
    id: str
    gstin: str
    invoice_no: str
    invoice_date: date | None
    total: Decimal
    tax: Decimal


@dataclass
class MatchResult2B:
    lines: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # 2B line id → (status, invoice id)
    missing_in_2b: list[str] = field(default_factory=list)  # book invoice ids
    itc_at_risk: Decimal = Decimal("0")


def _key(gstin: str, number: str, day: date | None) -> tuple[str, str, str]:
    return gstin.strip().upper(), normalize_invoice_no(number), fiscal_year(day) if day else ""


def match_2b(lines: list[TwoBIn], books: list[BookIn]) -> MatchResult2B:
    by_key = {}
    for b in books:
        by_key.setdefault(_key(b.gstin, b.invoice_no, b.invoice_date), b)
    result, found = MatchResult2B(), set()
    for ln in lines:
        book = by_key.get(_key(ln.gstin, ln.invoice_no, ln.invoice_date))
        if book is None:
            result.lines[ln.id] = ("not_in_books", None)
            continue
        found.add(book.id)
        status = "matched" if abs(book.total - ln.value) <= TOLERANCE else "amount_differs"
        result.lines[ln.id] = (status, book.id)
    for b in books:
        if b.id not in found:
            result.missing_in_2b.append(b.id)
            result.itc_at_risk += b.tax
    return result
