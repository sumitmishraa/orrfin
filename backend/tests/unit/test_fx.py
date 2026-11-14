"""Currency conversion and the regime-aware invoice checks (BUILD_PLAN §5 fx_rates, §6d). No database."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.entities.fx import convert
from app.modules.invoices.service import currency_code
from app.modules.invoices.validation import InvoiceFields, LineFields, validate

TODAY = date(2026, 11, 14)


def test_converted_money_is_rounded_once_half_up_to_two_decimals():
    assert convert(Decimal("100.00"), Decimal("22.63500000")) == Decimal("2263.50")
    assert convert(Decimal("1.00"), Decimal("0.12500000")) == Decimal("0.13")  # half goes up, not to even
    assert convert(Decimal("3.33"), Decimal("3.00000000")) == Decimal("9.99")


def test_a_float_is_refused_instead_of_being_rounded_away():
    with pytest.raises(TypeError):
        convert(100.10, Decimal("22.6"))
    with pytest.raises(TypeError):
        convert(Decimal("100.10"), 22.6)


def test_a_zero_or_negative_rate_is_refused():
    for bad in ("0", "-1.5"):
        with pytest.raises(ValueError):
            convert(Decimal("10.00"), Decimal(bad))


def test_the_printed_currency_becomes_a_code_and_is_never_guessed():
    assert currency_code("aed") == "AED"
    assert currency_code("₹") == "INR"
    assert currency_code("Dhs") == "AED"
    assert currency_code(None) == "INR"
    assert currency_code("dollars") == "INR"  # unreadable: stays the old default, finance corrects it


def _uae_fields(**changes) -> InvoiceFields:
    fields = InvoiceFields(
        vendor_gstin="100234567800003", buyer_gstin="100987654300003", invoice_no="DXB-1", invoice_date="2026-11-10",
        po_reference="PO-1", lines=[LineFields("Chairs", "CH-1", None, "10", "100.00", "1000.00")],
        subtotal="1000.00", cgst="0.00", sgst="0.00", igst="0.00", vat="50.00", total="1050.00", currency="AED")
    for name, value in changes.items():
        setattr(fields, name, value)
    return fields


def test_a_well_formed_uae_invoice_has_no_issues_under_the_uae_regime():
    assert validate(_uae_fields(), TODAY, "ae_vat") == []


def test_the_same_uae_invoice_is_flagged_under_the_indian_regime():
    codes = {i.code for i in validate(_uae_fields(), TODAY, "in_gst")}
    assert "GSTIN_FORMAT" in codes


def test_a_gstin_is_not_accepted_as_a_trn():
    issues = validate(_uae_fields(vendor_gstin="27AAACO1234F1Z5"), TODAY, "ae_vat")
    assert [(i.field, i.code) for i in issues] == [("vendor_gstin", "TRN_FORMAT")]


def test_vat_counts_toward_the_total():
    issues = validate(_uae_fields(total="1000.00"), TODAY, "ae_vat")
    assert [i.code for i in issues] == ["TOTAL_MISMATCH"]


def test_an_indian_invoice_without_a_vat_line_is_not_missing_a_field():
    fields = InvoiceFields(
        vendor_gstin="27AAACO1234F1Z5", buyer_gstin=None, invoice_no="INV-1", invoice_date="2026-11-10",
        po_reference="PO-1", lines=[LineFields("Chairs", "CH-1", "9403", "10", "100.00", "1000.00")],
        subtotal="1000.00", cgst="90.00", sgst="90.00", igst="0.00", total="1180.00")
    assert validate(fields, TODAY) == []


def test_a_currency_orrfin_does_not_handle_is_flagged():
    issues = validate(_uae_fields(currency="GBP"), TODAY, "ae_vat")
    assert [(i.field, i.code) for i in issues] == [("currency", "CURRENCY_UNSUPPORTED")]
