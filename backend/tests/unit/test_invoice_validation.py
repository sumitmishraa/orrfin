"""Post-extraction validation rules (BUILD_PLAN §7): schema, GSTIN format, dates, arithmetic."""

from datetime import date

import pytest

from app.modules.invoices.validation import (
    InvoiceFields,
    LineFields,
    fiscal_year,
    normalize_invoice_no,
    validate,
)

TODAY = date(2026, 10, 4)


def _clean(**overrides) -> InvoiceFields:
    fields = InvoiceFields(
        vendor_gstin="27AABCS4821K1Z9", buyer_gstin="27AADCO7734M1ZX", invoice_no="SOS/2026-27/0201",
        invoice_date="2026-09-10", po_reference="PUR-ORD-2026-00001",
        lines=[LineFields("A4 paper", "STAT-A4-75", "4802", "100", "285.00", "28500.00"),
               LineFields("Pens", "STAT-PEN-BLU50", "9608", "40", "450.00", "18000.00")],
        subtotal="46500.00", cgst="4185.00", sgst="4185.00", igst="0.00", total="54870.00",
    )
    for key, value in overrides.items():
        setattr(fields, key, value)
    return fields


def _codes(fields: InvoiceFields) -> set[str]:
    return {issue.code for issue in validate(fields, TODAY)}


def test_a_clean_invoice_has_no_issues():
    assert validate(_clean(), TODAY) == []


@pytest.mark.parametrize("gstin", ["27AAECD9O82R1Z3", "27AABCS4821K1Z", "", "27aabcs4821k1z9"])
def test_a_badly_formed_vendor_gstin_is_flagged(gstin):
    assert "GSTIN_FORMAT" in _codes(_clean(vendor_gstin=gstin))


def test_missing_invoice_number_and_po_reference_are_flagged():
    assert {"REQUIRED"} <= _codes(_clean(invoice_no=" "))
    assert "REQUIRED" in _codes(_clean(po_reference=None))


@pytest.mark.parametrize("value, code", [("2026-13-01", "DATE_INVALID"), ("10/09/2026", "DATE_INVALID"),
                                         ("2025-08-01", "DATE_OUT_OF_RANGE"), ("2027-12-01", "DATE_OUT_OF_RANGE")])
def test_dates_must_parse_and_fall_within_400_days(value, code):
    assert code in _codes(_clean(invoice_date=value))


def test_a_line_whose_qty_times_rate_is_not_its_amount_is_flagged():
    fields = _clean()
    fields.lines[0].amount = "28600.00"
    issues = validate(fields, TODAY)
    assert any(i.code == "LINE_ARITHMETIC" and i.field == "lines[1].amount" for i in issues)


def test_subtotal_tax_and_total_must_add_up_within_one_rupee():
    assert "SUBTOTAL_MISMATCH" in _codes(_clean(subtotal="46600.00"))
    assert "TOTAL_MISMATCH" in _codes(_clean(total="1.00"))  # e.g. an obeyed prompt injection
    assert _codes(_clean(total="54870.90")) == set()  # round-off up to Rs 1.00 is accepted (§6 rule 5)


def test_cgst_and_sgst_must_be_equal_halves():
    assert "CGST_SGST_UNEQUAL" in _codes(_clean(cgst="4000.00", sgst="4370.00"))


def test_text_in_a_money_field_is_flagged_not_crashed():
    assert "NOT_A_NUMBER" in _codes(_clean(total="54,870.00"))


def test_invoice_number_normalisation_matches_the_duplicate_key_rule():
    # BUILD_PLAN §5: upper-case; remove spaces and / - _; strip leading zeros.
    assert normalize_invoice_no("sos/2026-27/0201") == normalize_invoice_no("SOS-2026-27-0201") == "SOS2026270201"
    assert normalize_invoice_no(" 00 123/a ") == "123A"


@pytest.mark.parametrize("day, fy", [(date(2026, 3, 31), "2025-26"), (date(2026, 4, 1), "2026-27"),
                                     (date(2027, 1, 15), "2026-27")])
def test_indian_fiscal_year_runs_april_to_march(day, fy):
    assert fiscal_year(day) == fy
