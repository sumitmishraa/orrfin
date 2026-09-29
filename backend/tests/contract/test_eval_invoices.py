"""Checks on the Step 6 evaluation set in evals/extraction/ (PROMPTS Step 6, BUILD_PLAN §6, §7).

Proves the 12 PDFs open and show the numbers in their answer keys, that every answer key
adds up to the paisa, and that each scenario really exercises the rule it claims to,
by re-deriving the expected exception from the Step 4 ERP fixtures (not from the generator).
"""

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.config import REPO_ROOT

EVAL_DIR = REPO_ROOT / "evals" / "extraction"
FIXTURES = REPO_ROOT / "seed" / "erpnext"
GSTIN_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")  # BUILD_PLAN §6 rule 7
CENT = Decimal("0.01")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


KEYS = {p.stem: _json(p) for p in sorted(EVAL_DIR.glob("*.json"))}
SUPPLIERS = {s["name"]: s for s in _json(FIXTURES / "suppliers.json")["data"]}
POS = {po["name"]: po for po in _json(FIXTURES / "purchase_orders.json")["data"]}


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _po_line(key: dict, item_code: str) -> dict | None:
    po = POS[key["expected_extraction"]["po_reference"]]
    return next((i for i in po["items"] if i["item_code"] == item_code), None)


def _pdf_text(stem: str) -> str:
    reader = PdfReader(EVAL_DIR / f"{stem}.pdf")
    return "\n".join(page.extract_text() for page in reader.pages)


def _inr(value: str) -> str:
    whole, frac = value.split(".")
    head, tail, groups = whole[:-3], whole[-3:], []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail]) + "." + frac


def test_there_are_twelve_pdfs_each_with_an_answer_key():
    pdfs = sorted(p.stem for p in EVAL_DIR.glob("*.pdf"))
    assert len(pdfs) == 12
    assert pdfs == sorted(KEYS)
    assert sum("injection" in stem for stem in pdfs) == 1  # §7: exactly one injection PDF


@pytest.mark.parametrize("stem", sorted(KEYS))
def test_each_pdf_opens_and_shows_its_key_facts(stem):
    key = KEYS[stem]["expected_extraction"]
    text = _pdf_text(stem)

    for fact in (key["invoice_no"], key["vendor_gstin"], key["po_reference"], _inr(key["total"])):
        assert fact in text, f"{stem}: {fact!r} not found in the PDF text"


@pytest.mark.parametrize("stem", sorted(KEYS))
def test_each_answer_key_adds_up_to_the_paisa(stem):
    key = KEYS[stem]["expected_extraction"]
    lines = key["lines"]
    for line in lines:
        assert _money(Decimal(line["qty"]) * Decimal(line["rate"])) == Decimal(line["amount"])
    subtotal = sum(Decimal(l["amount"]) for l in lines)
    assert subtotal == Decimal(key["subtotal"])
    # Tax per line, rounded half-up, then summed (§6 rule 5).
    if Decimal(key["igst"]) > 0:
        assert Decimal(key["igst"]) == sum(_money(Decimal(l["amount"]) * Decimal("0.18")) for l in lines)
        assert Decimal(key["cgst"]) == Decimal(key["sgst"]) == 0
    else:
        half = sum(_money(Decimal(l["amount"]) * Decimal("0.09")) for l in lines)
        assert Decimal(key["cgst"]) == Decimal(key["sgst"]) == half
    tax = Decimal(key["cgst"]) + Decimal(key["sgst"]) + Decimal(key["igst"])
    assert subtotal + tax == Decimal(key["total"])


def test_every_invoice_refers_to_a_real_step_4_po():
    for stem, key in KEYS.items():
        assert key["expected_extraction"]["po_reference"] in POS, stem


# --- Each scenario really tests what it says, derived from the ERP fixtures --------------------

def _vendor_matches_po(key: dict) -> bool:
    po = POS[key["expected_extraction"]["po_reference"]]
    return SUPPLIERS[po["supplier"]]["gstin"] == key["expected_extraction"]["vendor_gstin"]


def _price_ok(key: dict) -> bool:
    for line in key["expected_extraction"]["lines"]:
        po_line = _po_line(key, line["item_code"])
        if po_line and abs(Decimal(line["rate"]) - Decimal(str(po_line["rate"]))) / Decimal(str(po_line["rate"])) > Decimal("0.02"):
            return False
    return True


def _all_lines_pair(key: dict) -> bool:
    return all(_po_line(key, l["item_code"]) for l in key["expected_extraction"]["lines"])


def _tax_type_ok(key: dict) -> bool:
    ex = key["expected_extraction"]
    same_state = ex["vendor_gstin"][:2] == ex["buyer_gstin"][:2]
    return (Decimal(ex["igst"]) == 0) if same_state else (Decimal(ex["cgst"]) == Decimal(ex["sgst"]) == 0)


def test_the_clean_match_passes_every_derivable_rule():
    key = KEYS["01-clean-match"]
    assert key["expected_match"]["outcome"] == "matched"
    assert _vendor_matches_po(key) and _price_ok(key) and _all_lines_pair(key) and _tax_type_ok(key)
    assert GSTIN_FORMAT.match(key["expected_extraction"]["vendor_gstin"])
    for line in key["expected_extraction"]["lines"]:
        assert Decimal(line["qty"]) <= Decimal(str(_po_line(key, line["item_code"])["received_qty"]))


def test_price_variance_is_above_the_two_percent_tolerance():
    key = KEYS["02-price-variance-7pct"]
    assert not _price_ok(key) and "PRICE_VARIANCE" in key["expected_match"]["exceptions"]


def test_over_receipt_bills_more_than_was_received():
    key = KEYS["03-over-receipt-qty"]
    line = key["expected_extraction"]["lines"][0]
    assert Decimal(line["qty"]) > Decimal(str(_po_line(key, line["item_code"])["received_qty"]))


def test_partial_receipt_first_fits_and_second_exceeds_cumulatively():
    first, second = KEYS["04-partial-receipt-first"], KEYS["05-partial-receipt-second"]
    code = first["expected_extraction"]["lines"][0]["item_code"]
    received = Decimal(str(_po_line(first, code)["received_qty"]))
    q1 = Decimal(first["expected_extraction"]["lines"][0]["qty"])
    q2 = Decimal(second["expected_extraction"]["lines"][0]["qty"])
    assert q1 <= received < q1 + q2
    assert first["expected_match"]["outcome"] == "matched"
    assert "QTY_EXCEEDS_RECEIPT" in second["expected_match"]["exceptions"]


def test_duplicate_number_normalises_to_invoice_01_with_the_same_total():
    def norm(no: str) -> str:  # §5: upper-case, drop spaces and / - _, strip leading zeros
        return re.sub(r"[\s/\-_]", "", no.upper()).lstrip("0")

    original, dup = KEYS["01-clean-match"]["expected_extraction"], KEYS["06-duplicate-number"]["expected_extraction"]
    assert original["invoice_no"] != dup["invoice_no"]
    assert norm(original["invoice_no"]) == norm(dup["invoice_no"])
    assert (original["vendor_gstin"], original["total"]) == (dup["vendor_gstin"], dup["total"])


def test_bad_gstin_fails_the_format_and_the_vendor_check():
    key = KEYS["07-bad-gstin"]
    assert not GSTIN_FORMAT.match(key["expected_extraction"]["vendor_gstin"])
    assert not _vendor_matches_po(key)


def test_igst_is_charged_on_a_same_state_supply():
    assert not _tax_type_ok(KEYS["08-igst-instead-of-cgst-sgst"])


def test_vendor_mismatch_has_a_valid_gstin_that_is_not_the_po_vendors():
    key = KEYS["09-vendor-mismatch"]
    assert GSTIN_FORMAT.match(key["expected_extraction"]["vendor_gstin"]) and not _vendor_matches_po(key)


def test_closed_po_is_closed_in_the_erp():
    assert POS[KEYS["10-closed-po"]["expected_extraction"]["po_reference"]]["status"] == "Closed"


def test_unpaired_line_has_no_po_line():
    assert not _all_lines_pair(KEYS["11-unpaired-line"])


def test_the_injection_is_in_the_pdf_but_not_in_the_answer_key():
    text = _pdf_text("12-prompt-injection")
    key = KEYS["12-prompt-injection"]
    assert "ignore all previous instructions" in text.lower()
    assert Decimal(key["expected_extraction"]["total"]) > 1
    assert key["expected_match"]["outcome"] == "matched"


@pytest.mark.parametrize("stem", sorted(KEYS))
def test_every_other_scenario_is_otherwise_clean(stem):
    """Guards against a scenario accidentally tripping a second rule it doesn't declare."""
    key = KEYS[stem]
    declared = set(key["expected_match"]["exceptions"])
    if "PRICE_VARIANCE" not in declared:
        assert _price_ok(key), stem
    if "LINE_UNPAIRED" not in declared:
        assert _all_lines_pair(key), stem
    if "TAX_TYPE_MISMATCH" not in declared:
        assert _tax_type_ok(key), stem
    if "VENDOR_MISMATCH" not in declared:
        assert _vendor_matches_po(key), stem
