"""Shared ERP adapter contract (BUILD_PLAN §4 connector rules, §8; PROMPTS Step 12).

Every registered adapter (tests/contract/erp_adapters.py), simulated or live-seeded, must give
Orrfin the same canonical data: the 5 vendors with valid GSTINs, the 8 POs with Decimal money that
adds up to the canonical totals, the 8 receipts with the right quantities, and drafts and lookups
that behave as its capabilities() say. A read-only (sandbox) adapter must refuse writes clearly.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.erp_demo.canonical import dataset
from app.ports.erp import DraftBill, DraftLine, DraftPo, ErpNotSupported, ErpPurchaseOrder
from tests.contract.erp_adapters import ADAPTERS

DATA = dataset()


@pytest.fixture(params=sorted(ADAPTERS), ids=sorted(ADAPTERS))
def adapter(request):
    return ADAPTERS[request.param]()


def _po_by_number(adapter) -> dict[str, ErpPurchaseOrder]:
    pos = adapter.list_purchase_orders()
    return {(po.po_number or po.erp_ref): po for po in pos}


def test_connection_check_passes(adapter):
    check = adapter.test_connection()
    assert check.ok, check.steps
    assert check.steps and all(s.detail for s in check.steps)


def test_vendors_match_the_canonical_set(adapter):
    vendors = adapter.list_vendors()
    assert {v.gstin for v in vendors} >= {v.gstin for v in DATA.vendors}
    for vendor in vendors:
        if vendor.gstin:
            assert vendor.state_code == vendor.gstin[:2]
        assert vendor.modified.tzinfo is not None


def test_purchase_orders_match_canonical_totals_in_decimal(adapter):
    pos = _po_by_number(adapter)
    vendors = {v.erp_ref: v for v in adapter.list_vendors()}
    for canon in DATA.purchase_orders:
        po = pos.get(canon.number)
        assert po is not None, f"{canon.number} missing"
        assert vendors[po.vendor_ref].gstin == canon.vendor.gstin
        assert po.net_total == canon.net_total and po.grand_total == canon.grand_total
        assert isinstance(po.grand_total, Decimal)
        assert po.status == canon.status
        assert [(l.item_code, l.qty, l.rate, l.amount) for l in po.lines] == \
               [(l.item_code, l.qty, l.rate, l.amount) for l in canon.lines]
        assert all(l.tax_rate == Decimal("18") for l in po.lines)
        assert all(isinstance(l.qty, Decimal) and isinstance(l.rate, Decimal) for l in po.lines)


def test_receipts_point_at_po_lines_with_canonical_quantities(adapter):
    pos = _po_by_number(adapter)
    line_owner = {line.erp_ref: (number, line.item_code) for number, po in pos.items() for line in po.lines}
    received: dict[tuple[str, str], Decimal] = {}
    for receipt in adapter.list_receipts():
        for line in receipt.lines:
            assert line.po_line_ref in line_owner, f"receipt line {line.erp_ref} points at no PO line"
            key = line_owner[line.po_line_ref]
            received[key] = received.get(key, Decimal("0")) + line.qty_received
    for canon in DATA.purchase_orders:
        for index, line in enumerate(canon.lines):
            assert received.get((canon.number, line.item_code), Decimal("0")) == canon.received(index)


def _draft_bill(adapter, invoice_no: str) -> DraftBill:
    po = _po_by_number(adapter)[DATA.purchase_orders[0].number]
    line = po.lines[0]
    return DraftBill(idempotency_key="a" * 64, vendor_ref=po.vendor_ref, vendor_gstin=DATA.purchase_orders[0].vendor.gstin,
                     supplier_invoice_no=invoice_no, invoice_date=date(2026, 9, 9), po_ref=po.erp_ref,
                     lines=[DraftLine(item_code=line.item_code, description=line.description, qty=line.qty,
                                      rate=line.rate, amount=line.amount, tax_rate=line.tax_rate,
                                      po_line_ref=line.erp_ref)],
                     net_total=line.amount, cgst=Decimal("2565.00"), sgst=Decimal("2565.00"),
                     grand_total=line.amount + Decimal("5130.00"))


def _draft_po(adapter, key: str) -> DraftPo:
    vendor = next(v for v in adapter.list_vendors() if v.gstin == DATA.vendors[1].gstin)
    line = DATA.purchase_orders[1].lines[0]
    return DraftPo(idempotency_key=key, request_number="PR-2026-0042", vendor_ref=vendor.erp_ref,
                   po_date=date(2026, 10, 1), schedule_date=date(2026, 10, 15),
                   lines=[DraftLine(item_code=line.item_code, description=line.item_name, uom=line.uom,
                                    qty=Decimal("3"), rate=line.rate, amount=line.rate * 3, tax_rate=line.tax_rate)])


def test_draft_bill_then_lookup_finds_exactly_that_draft(adapter):
    caps = adapter.capabilities()
    if not caps.can_write_bill:
        with pytest.raises(ErpNotSupported):
            adapter.create_draft_bill(_draft_bill(adapter, "CT-INV-001"))
        return
    bill = _draft_bill(adapter, "CT-INV-001")
    assert adapter.find_bill(bill.vendor_ref, bill.supplier_invoice_no) is None
    created = adapter.create_draft_bill(bill)
    assert created.erp_doc_name
    assert adapter.find_bill(bill.vendor_ref, bill.supplier_invoice_no) == created.erp_doc_name
    assert adapter.find_bill(bill.vendor_ref, "SOME-OTHER-NO") is None
    # A draft bill is not a submitted document, so it never shows up in the mirror.
    assert all(created.erp_doc_name != po.erp_ref for po in adapter.list_purchase_orders())


def test_draft_po_then_lookup_finds_exactly_that_draft(adapter):
    caps = adapter.capabilities()
    key = "b" * 64
    if not caps.can_write_po:
        with pytest.raises(ErpNotSupported):
            adapter.create_draft_po(_draft_po(adapter, key))
        return
    before = {po.erp_ref for po in adapter.list_purchase_orders()}
    assert adapter.find_po(key) is None
    created = adapter.create_draft_po(_draft_po(adapter, key))
    assert adapter.find_po(key) == created.erp_doc_name
    assert adapter.find_po("c" * 64) is None
    # Drafts stay out of the mirror until a person submits them in the ERP.
    assert {po.erp_ref for po in adapter.list_purchase_orders()} == before


def test_capabilities_explain_drafts_in_plain_words(adapter):
    caps = adapter.capabilities()
    assert caps.label in ("live", "sandbox", "simulated")
    assert caps.draft_bill_means and caps.draft_po_means
    if not (caps.can_write_bill and caps.can_write_po):
        assert caps.write_note
