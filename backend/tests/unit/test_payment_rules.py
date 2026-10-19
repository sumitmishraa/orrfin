"""TDS and payment-risk rules (BUILD_PLAN §6b, §6c; PROMPTS Step 25). Pure functions, Decimal money.

TDS rates and thresholds follow the Income-tax Act as commonly applied for FY 2026-27 and are
TO BE CONFIRMED BY A CA before any pilot (§12).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.payments.risk import PaymentFacts, check_payment, has_block
from app.modules.payments.tds import TdsInput, compute_tds

D = Decimal
PAN = "AAKFK3310P"


def tds(section, base, before="0", payee="company", pan=PAN, kind="professional"):
    return compute_tds(TdsInput(section=section, payee_type=payee, pan=pan, base=D(base),
                                paid_before_in_fy=D(before), j_kind=kind))


# --- TDS --------------------------------------------------------------------------------------------------

def test_no_section_means_no_tds():
    result = tds(None, "100000.00")
    assert result.tds == D("0.00") and result.rate == D("0")


def test_194c_two_percent_for_a_company_one_percent_for_an_individual():
    assert tds("194C", "50000.00").tds == D("1000.00")
    assert tds("194C", "50000.00", payee="individual").tds == D("500.00")


def test_194c_thresholds_single_30000_or_year_100000():
    assert tds("194C", "30000.00").tds == D("0.00")  # not above ₹30,000, year total small
    assert tds("194C", "30000.01").tds == D("600.00")  # 2% of 30,000.01 = 600.0002 → ₹600
    assert tds("194C", "20000.00", before="85000.00").tds == D("400.00")  # year crosses ₹1,00,000


def test_194j_professional_ten_percent_technical_two_percent_above_50000_a_year():
    assert tds("194J", "40000.00").tds == D("0.00")
    assert tds("194J", "40000.00", before="20000.00").tds == D("4000.00")
    assert tds("194J", "60000.00", kind="technical").tds == D("1200.00")


def test_194q_only_on_the_part_above_50_lakh():
    assert tds("194Q", "1000000.00", before="4500000.00").tds == D("500.00")  # 0.1% of ₹5,00,000
    assert tds("194Q", "1000000.00", before="1000000.00").tds == D("0.00")


def test_no_valid_pan_means_twenty_percent_or_five_for_194q():
    assert tds("194C", "50000.00", pan=None).tds == D("10000.00")
    assert tds("194C", "50000.00", pan="BADPAN").rate == D("20")
    assert tds("194Q", "1000000.00", before="5000000.00", pan=None).tds == D("50000.00")


def test_tds_is_rounded_to_the_nearest_rupee():
    assert tds("194C", "33333.33").tds == D("667.00")  # 666.6666 → ₹667
    assert tds("194C", "33324.75").tds == D("666.00")  # 666.495 → ₹666


# --- Payment risk -----------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def facts(**overrides):
    base = dict(invoice_status="approved", invoice_total=D("118000.00"), already_paid=D("0"),
                gross=D("118000.00"), has_profile=True, bank_verified=True, bank_changed_at=NOW - timedelta(days=200),
                bank_shared_with_other_vendor=False, tds_section="194C", pan=PAN, first_payment=False,
                bill_confirmed_in_erp=True, missing_from_gstr2b=None, now=NOW)
    base.update(overrides)
    return PaymentFacts(**base)


def codes(results, level):
    return {r["code"] for r in results if r["level"] == level}


def test_a_clean_payment_has_no_blocks_or_holds():
    results = check_payment(facts())
    assert codes(results, "block") == set() and codes(results, "hold") == set()


def test_blocks():
    assert "INVOICE_NOT_APPROVED" in codes(check_payment(facts(invoice_status="exception")), "block")
    assert "ALREADY_PAID" in codes(check_payment(facts(already_paid=D("118000.00"))), "block")
    assert "AMOUNT_EXCEEDS_INVOICE" in codes(check_payment(facts(already_paid=D("100000.00"))), "block")
    assert "NO_PAYMENT_PROFILE" in codes(check_payment(facts(has_profile=False)), "block")
    assert "BANK_UNVERIFIED" in codes(check_payment(facts(bank_verified=False)), "block")
    assert "BANK_SHARED" in codes(check_payment(facts(bank_shared_with_other_vendor=True)), "block")
    assert has_block(check_payment(facts(bank_verified=False)))


def test_holds_need_a_reason_but_do_not_block():
    results = check_payment(facts(bank_changed_at=NOW - timedelta(days=5), first_payment=True,
                                  bill_confirmed_in_erp=False, missing_from_gstr2b=True, pan=None))
    assert codes(results, "hold") == {"BANK_CHANGED_RECENTLY", "FIRST_PAYMENT", "BILL_NOT_IN_ERP",
                                      "NOT_IN_GSTR2B", "PAN_MISSING"}
    assert not has_block(results)


def test_a_bank_change_31_days_ago_is_no_longer_a_hold():
    assert "BANK_CHANGED_RECENTLY" not in codes(check_payment(facts(bank_changed_at=NOW - timedelta(days=31))), "hold")


def test_bank_file_cells_cannot_become_spreadsheet_formulas():
    from app.modules.payments.service import csv_safe

    assert csv_safe("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert csv_safe("+91 pay") == "'+91 pay" and csv_safe("Shreeji Office") == "Shreeji Office"
