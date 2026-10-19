"""GSTR-2B matching rules (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Pure, Decimal money. Matching only."""

from datetime import date
from decimal import Decimal

from app.modules.gst.match import BookIn, TwoBIn, match_2b

D = Decimal
GSTIN = "27AABCS4821K1Z9"


def two_b(n, inv, value, tax="8370.00", gstin=GSTIN):
    return TwoBIn(id=f"t{n}", gstin=gstin, invoice_no=inv, invoice_date=date(2026, 9, 10), value=D(value), tax=D(tax))


def book(n, inv, total, tax="8370.00", gstin=GSTIN):
    return BookIn(id=f"i{n}", gstin=gstin, invoice_no=inv, invoice_date=date(2026, 9, 10), total=D(total), tax=D(tax))


def test_same_supplier_number_and_year_match_even_when_written_differently():
    result = match_2b([two_b(1, "SOS/2026-27/0201", "54870.00")], [book(1, "sos 2026-27_0201", "54870.00")])
    assert result.lines == {"t1": ("matched", "i1")} and result.missing_in_2b == []


def test_amounts_differing_by_more_than_one_rupee_are_flagged():
    result = match_2b([two_b(1, "INV-1", "54900.00")], [book(1, "INV-1", "54870.00")])
    assert result.lines["t1"] == ("amount_differs", "i1")
    result = match_2b([two_b(1, "INV-1", "54870.90")], [book(1, "INV-1", "54870.00")])
    assert result.lines["t1"] == ("matched", "i1")  # within ₹1 round-off


def test_invoices_in_the_books_but_not_in_2b_put_itc_at_risk():
    result = match_2b([], [book(1, "INV-1", "54870.00", tax="8370.00")])
    assert result.missing_in_2b == ["i1"] and result.itc_at_risk == D("8370.00")


def test_2b_lines_not_in_the_books_are_listed():
    result = match_2b([two_b(1, "OTHER-9", "1000.00")], [])
    assert result.lines["t1"] == ("not_in_books", None)


def test_a_different_supplier_never_matches():
    result = match_2b([two_b(1, "INV-1", "54870.00", gstin="29AAKFK3310P1ZY")], [book(1, "INV-1", "54870.00")])
    assert result.lines["t1"] == ("not_in_books", None) and result.missing_in_2b == ["i1"]
