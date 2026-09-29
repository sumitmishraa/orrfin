"""Contract tests: the fake ERPNext fixtures look like ERPNext and translate cleanly (PROMPTS Step 4).

When the live adapter arrives (Step 11), the same checks run against recorded live
responses, so the fake and the real ERP are held to one contract.
"""

from decimal import Decimal

import pytest

from app.adapters.erpnext import load_erpnext_json
from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT

FIXTURES = REPO_ROOT / "seed" / "erpnext"
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _raw(filename: str) -> list[dict]:
    return load_erpnext_json((FIXTURES / filename).read_text(encoding="utf-8"))["data"]


def _gstin_is_valid(gstin: str) -> bool:
    total = 0
    for i, ch in enumerate(gstin[:14]):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return len(gstin) == 15 and gstin[14] == GSTIN_CHARS[(36 - total % 36) % 36]


@pytest.fixture(scope="module")
def adapter() -> FakeErpnextAdapter:
    return FakeErpnextAdapter(FIXTURES)


@pytest.mark.parametrize("filename, required", [
    ("suppliers.json", {"name", "supplier_name", "gstin", "modified", "disabled"}),
    ("purchase_orders.json", {"name", "supplier", "transaction_date", "status", "docstatus",
                              "net_total", "grand_total", "modified", "items", "taxes"}),
    ("purchase_receipts.json", {"name", "supplier", "posting_date", "docstatus", "modified", "items"}),
])
def test_documents_carry_the_erpnext_fields_the_adapter_reads(filename, required):
    for doc in _raw(filename):
        assert required <= doc.keys(), f"{doc['name']} is missing {required - doc.keys()}"


def test_fixture_counts_match_the_step_4_brief(adapter):
    assert len(adapter.list_vendors()) == 5
    assert len(adapter.list_purchase_orders()) == 8
    assert len(adapter.list_receipts()) >= 1


def test_every_vendor_has_a_valid_gstin_and_state_code(adapter):
    for vendor in adapter.list_vendors():
        assert _gstin_is_valid(vendor.gstin), vendor.gstin
        assert vendor.state_code == vendor.gstin[:2]
        assert vendor.modified.tzinfo is not None


def test_po_totals_add_up_exactly_in_decimal(adapter):
    for po in adapter.list_purchase_orders():
        assert all(isinstance(line.amount, Decimal) for line in po.lines)
        assert sum(line.qty * line.rate for line in po.lines) == po.net_total
        assert sum(line.amount for line in po.lines) == po.net_total
        assert po.net_total + po.tax_total == po.grand_total
        assert all(line.tax_rate == Decimal("18") for line in po.lines)


def test_receipt_lines_point_at_real_po_lines_and_never_exceed_the_order(adapter):
    po_lines = {line.erp_ref: line for po in adapter.list_purchase_orders() for line in po.lines}
    received: dict[str, Decimal] = {}
    for receipt in adapter.list_receipts():
        for line in receipt.lines:
            assert line.po_line_ref in po_lines, f"{receipt.erp_ref} points at unknown PO line"
            received[line.po_line_ref] = received.get(line.po_line_ref, Decimal("0")) + line.qty_received
    for ref, qty in received.items():
        assert qty <= po_lines[ref].qty


def test_fixtures_include_partial_unreceived_and_closed_pos(adapter):
    pos = adapter.list_purchase_orders()
    received = {}
    for receipt in adapter.list_receipts():
        for line in receipt.lines:
            received[line.po_line_ref] = received.get(line.po_line_ref, 0) + line.qty_received
    partial = [po for po in pos if any(0 < received.get(l.erp_ref, 0) < l.qty for l in po.lines)]
    unreceived = [po for po in pos if not any(received.get(l.erp_ref) for l in po.lines)]

    assert len(partial) >= 2
    assert len(unreceived) >= 1
    assert any(po.status == "closed" for po in pos)


def test_drafts_and_cancelled_documents_are_not_returned(tmp_path):
    import json

    for filename in ("suppliers.json", "purchase_orders.json", "purchase_receipts.json"):
        (tmp_path / filename).write_text((FIXTURES / filename).read_text(encoding="utf-8"), encoding="utf-8")
    orders = json.loads((tmp_path / "purchase_orders.json").read_text())
    orders["data"][0]["docstatus"] = 0  # draft
    orders["data"][1]["docstatus"] = 2  # cancelled
    (tmp_path / "purchase_orders.json").write_text(json.dumps(orders))

    assert len(FakeErpnextAdapter(tmp_path).list_purchase_orders()) == 6
