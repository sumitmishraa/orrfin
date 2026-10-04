"""The matching engine, rule by rule (BUILD_PLAN §6) and the §11 M4 scenarios (PROMPTS Step 8).

Pure tests: the engine takes plain data and returns a result, so no database is needed.
Each test changes one thing from a clean invoice, so a failure points at one rule.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.modules.matching.config import RULE_SET_VERSION, Tolerances
from app.modules.matching.engine import is_stale, match
from app.modules.matching.types import InvoiceIn, InvoiceLineIn, MatchInput, PoIn, PoLineIn, PriorInvoice

D = Decimal
MH = "27AABCS4821K1Z9"  # Maharashtra vendor (same state as the buyer)
KA = "29AAKFK3310P1Z5"  # Karnataka vendor (inter-state)


def _po_lines(**overrides) -> list[PoLineIn]:
    lines = [
        PoLineIn(id="L1", erp_ref="r1", item_code="STAT-A4-75", hsn="4802", qty=D("100"), rate=D("285.00"),
                 tax_rate=D("18"), received_to_date=D("100"), invoiced_to_date=D("0")),
        PoLineIn(id="L2", erp_ref="r2", item_code="STAT-PEN-BLU50", hsn="9608", qty=D("40"), rate=D("450.00"),
                 tax_rate=D("18"), received_to_date=D("40"), invoiced_to_date=D("0")),
    ]
    for key, value in overrides.items():
        line_no, attr = key.split("__")
        lines[int(line_no) - 1] = replace(lines[int(line_no) - 1], **{attr: value})
    return lines


def _invoice(**overrides) -> InvoiceIn:
    invoice = InvoiceIn(
        id="INV", vendor_gstin=MH, buyer_state_code="27", invoice_no_norm="SOS2026270201", fiscal_year="2026-27",
        document_sha256="aaa",
        lines=[InvoiceLineIn(1, "A4 paper", "STAT-A4-75", "4802", D("100"), D("285.00"), D("28500.00")),
               InvoiceLineIn(2, "Pens", "STAT-PEN-BLU50", "9608", D("40"), D("450.00"), D("18000.00"))],
        subtotal=D("46500.00"), cgst=D("4185.00"), sgst=D("4185.00"), igst=D("0.00"), total=D("54870.00"),
    )
    return replace(invoice, **overrides)


def _run(invoice: InvoiceIn | None = None, *, po: PoIn | None | str = "default", lines=None, priors=()):
    po_in = PoIn(erp_ref="PUR-ORD-2026-00001", status="to_bill", vendor_gstin=MH) if po == "default" else po
    return match(MatchInput(invoice=invoice or _invoice(), po=po_in, po_lines=lines if lines is not None else _po_lines(),
                            prior_invoices=list(priors), tolerances=Tolerances()))


def _failed(result) -> set[str]:
    return {r.code for r in result.rule_results if r.status == "fail"}


# --- §11 M4 scenarios ---------------------------------------------------------------------------

def test_clean_match():
    result = _run()
    assert result.outcome == "matched"
    assert _failed(result) == set()
    assert result.amount_at_risk == D("0") and result.risk_score == 0
    assert result.rule_set_version == RULE_SET_VERSION
    assert result.pairings == {1: ("L1", "item_code"), 2: ("L2", "item_code")}


def test_price_variance_above_two_percent():
    inv = _invoice(lines=[InvoiceLineIn(1, "A4", "STAT-A4-75", "4802", D("100"), D("305.00"), D("30500.00")),
                          InvoiceLineIn(2, "Pens", "STAT-PEN-BLU50", "9608", D("40"), D("450.00"), D("18000.00"))],
                   subtotal=D("48500.00"), cgst=D("4365.00"), sgst=D("4365.00"), total=D("57230.00"))
    result = _run(inv)
    assert _failed(result) == {"PRICE_VARIANCE"}
    assert result.amount_at_risk == D("2000.00")  # (305 - 285) × 100


def test_price_within_two_percent_is_accepted():
    inv = _invoice(lines=[InvoiceLineIn(1, "A4", "STAT-A4-75", "4802", D("100"), D("290.00"), D("29000.00")),
                          InvoiceLineIn(2, "Pens", "STAT-PEN-BLU50", "9608", D("40"), D("450.00"), D("18000.00"))],
                   subtotal=D("47000.00"), cgst=D("4230.00"), sgst=D("4230.00"), total=D("55460.00"))
    assert _run(inv).outcome == "matched"  # 1.75% above


def test_over_receipt_quantity():
    result = _run(lines=_po_lines(**{"1__received_to_date": D("80")}))
    assert _failed(result) == {"QTY_EXCEEDS_RECEIPT"}
    assert result.amount_at_risk == D("5700.00")  # 20 not received × 285


def test_partial_receipt_then_second_invoice_exceeds_cumulatively():
    # 100 received; 60 already invoiced on an earlier, matched invoice; this one bills 100 more.
    result = _run(lines=_po_lines(**{"1__invoiced_to_date": D("60")}))
    assert _failed(result) == {"QTY_EXCEEDS_RECEIPT"}
    assert result.amount_at_risk == D("17100.00")  # 60 too many × 285


def test_duplicate_key_only_is_a_warning():
    prior = PriorInvoice(id="OLD", vendor_gstin=MH, invoice_no_norm="SOS2026270201", fiscal_year="2026-27",
                         total=D("99.00"), document_sha256="bbb")
    result = _run(priors=[prior])
    assert result.outcome == "matched"
    assert any(r.code == "DUPLICATE_SUSPECTED" and r.status == "warn" for r in result.rule_results)


def test_duplicate_key_and_total_blocks():
    prior = PriorInvoice(id="OLD", vendor_gstin=MH, invoice_no_norm="SOS2026270201", fiscal_year="2026-27",
                         total=D("54870.00"), document_sha256="bbb")
    result = _run(priors=[prior])
    assert _failed(result) == {"DUPLICATE_BLOCKING"}
    assert result.amount_at_risk == D("54870.00")


def test_same_file_reuploaded_blocks():
    prior = PriorInvoice(id="OLD", vendor_gstin=KA, invoice_no_norm="OTHER", fiscal_year="2026-27",
                         total=D("1.00"), document_sha256="aaa")
    assert "DUPLICATE_BLOCKING" in _failed(_run(priors=[prior]))


def test_bad_gstin_format():
    result = _run(_invoice(vendor_gstin="27AABCS48O1K1Z9"))
    assert {"GSTIN_INVALID", "VENDOR_MISMATCH"} <= _failed(result)


def test_gstin_check_character_is_advisory_only():
    result = _run(_invoice(vendor_gstin="27AABCS4821K1Z8"), po=PoIn("PUR-ORD-2026-00001", "to_bill", "27AABCS4821K1Z8"))
    assert result.outcome == "matched"
    assert any(r.code == "GSTIN_CHECKSUM" and r.status == "warn" for r in result.rule_results)


def test_igst_charged_on_a_same_state_supply():
    result = _run(_invoice(cgst=D("0.00"), sgst=D("0.00"), igst=D("8370.00")))
    assert _failed(result) == {"TAX_TYPE_MISMATCH"}
    assert result.amount_at_risk == D("8370.00")


def test_cgst_sgst_charged_on_an_inter_state_supply():
    inv = _invoice(vendor_gstin=KA)
    result = _run(inv, po=PoIn("PUR-ORD-2026-00001", "to_bill", KA))
    assert _failed(result) == {"TAX_TYPE_MISMATCH"}


def test_vendor_mismatch():
    result = _run(_invoice(vendor_gstin=KA, cgst=D("0.00"), sgst=D("0.00"), igst=D("8370.00")))
    assert _failed(result) == {"VENDOR_MISMATCH"}
    assert result.amount_at_risk == D("54870.00")


@pytest.mark.parametrize("status", ["closed", "completed", "on_hold"])
def test_po_not_open(status):
    result = _run(po=PoIn("PUR-ORD-2026-00001", status, MH))
    assert _failed(result) == {"PO_NOT_OPEN"}


def test_po_not_found():
    result = _run(po=None, lines=[])
    assert _failed(result) == {"PO_NOT_FOUND"}
    assert result.amount_at_risk == D("54870.00")


def test_unpaired_line():
    extra = InvoiceLineIn(3, "Installation", "SVC-INSTALL", "998719", D("1"), D("1000.00"), D("1000.00"))
    inv = _invoice(lines=_invoice().lines + [extra], subtotal=D("47500.00"), cgst=D("4275.00"),
                   sgst=D("4275.00"), total=D("56050.00"))
    result = _run(inv)
    assert _failed(result) == {"LINE_UNPAIRED"}
    assert result.amount_at_risk == D("1000.00")


def test_one_paisa_rounding_is_accepted_and_reported_as_round_off():
    result = _run(_invoice(total=D("54870.01")))
    assert result.outcome == "matched"
    assert any(r.code == "ROUND_OFF" and r.status == "info" for r in result.rule_results)


def test_arithmetic_beyond_one_rupee_fails():
    assert _failed(_run(_invoice(total=D("54872.00")))) == {"ARITHMETIC_MISMATCH"}
    assert "ARITHMETIC_MISMATCH" in _failed(_run(_invoice(subtotal=D("46600.00"))))


def test_stale_po_is_detected():
    snapshot = {"po": "2026-09-01T16:30:00+05:30", "receipts": {"MAT-PRE-1": "2026-09-07T18:05:00+05:30"}}
    assert not is_stale(snapshot, dict(snapshot))
    assert is_stale(snapshot, {**snapshot, "po": "2026-09-29T09:00:00+05:30"})
    assert is_stale(snapshot, {**snapshot, "receipts": {"MAT-PRE-1": "2026-09-07T18:05:00+05:30", "MAT-PRE-9": "x"}})


# --- Pairing order (§6 rule 1) -----------------------------------------------------------------

def test_pairing_prefers_an_explicit_po_line_reference():
    line = replace(_invoice().lines[0], item_code="WRONG", po_line_ref="r1")
    result = _run(_invoice(lines=[line, _invoice().lines[1]]))
    assert result.pairings[1] == ("L1", "po_line_ref")


def test_pairing_falls_back_to_hsn_and_rate():
    line = replace(_invoice().lines[0], item_code=None)
    result = _run(_invoice(lines=[line, _invoice().lines[1]]))
    assert result.pairings[1] == ("L1", "hsn_rate") and result.outcome == "matched"


def test_ambiguous_pairing_is_unpaired_never_guessed():
    twin = PoLineIn(id="L3", erp_ref="r3", item_code="STAT-A4-80", hsn="4802", qty=D("100"), rate=D("285.00"),
                    tax_rate=D("18"), received_to_date=D("100"), invoiced_to_date=D("0"))
    line = replace(_invoice().lines[0], item_code=None)  # HSN 4802 at 285 fits two PO lines
    result = _run(_invoice(lines=[line, _invoice().lines[1]]), lines=_po_lines() + [twin])
    assert 1 not in result.pairings
    assert any(r.code == "LINE_UNPAIRED" and "more than one" in r.message for r in result.rule_results)


# --- Score and amount at risk ------------------------------------------------------------------

def test_amount_at_risk_never_exceeds_the_invoice_total_and_score_is_capped():
    inv = _invoice(vendor_gstin="BAD", igst=D("1.00"))
    result = _run(inv, po=PoIn("X", "closed", KA), lines=_po_lines(**{"1__received_to_date": D("0")}))
    assert result.amount_at_risk <= inv.total
    assert 0 < result.risk_score <= 100


def test_every_result_is_plain_data_for_the_explanation():
    result = _run(_invoice(total=D("1.00")))
    for rule in result.as_json():
        assert set(rule) >= {"rule", "code", "status", "message", "amount_at_risk"}
        assert isinstance(rule["amount_at_risk"], str)  # Decimal as text, never float
