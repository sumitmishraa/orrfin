"""§8 exactly once for a PO that covers several requests (Step 42, ADR 0012), against simulated ERPNext.

- Two employees' approved needs go on one Orrfin PO; Finance approves it; the ERP saves the draft PO and the
  reply is lost → the retry looks it up → exactly one ERP draft PO, carrying both requests.
- "Send to vendor" works once the draft is confirmed and quotes the ERP number.
- A person submits the PO in the ERP → the next sync links the mirrored PO back to the Orrfin PO.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.models import ApprovalPolicy, Category, ErpOutbox, PurchaseOrder, Vendor
from app.modules.erp_outbox import po as po_module
from app.modules.erp_outbox import service as outbox
from app.modules.sync.service import pull_from_erp
from app.seed_demo import POLICIES
from tests.conftest import login
from tests.failure.erp_write_cases import CASES, SavedThenTimedOut, drain_with_retries


@pytest.fixture
def team(db, factory):
    org = factory.org()
    org.intake_flow = "need_first"
    manager = factory.user(org, "approver", limit="500000", name="Manager")
    riya = factory.user(org, "requester", manager=manager, name="Riya")
    sameer = factory.user(org, "requester", manager=manager, name="Sameer")
    buyer = factory.user(org, "buyer", name="Buyer")
    finance = factory.user(org, "finance", limit="5000000", name="Finance")
    category = Category(org_id=org.id, name="IT hardware", buyer_id=buyer.id)
    db.add(category)
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()
    return {"org": org, "manager": manager, "riya": riya, "sameer": sameer, "buyer": buyer, "finance": finance,
            "category": category}


def _approved_po(client, db, monkeypatch, team, adapter) -> dict:
    org = team["org"]
    pull_from_erp(db, org.id, adapter)
    db.commit()
    monkeypatch.setattr(outbox, "get_adapter", lambda connection: adapter)
    monkeypatch.setattr(po_module, "get_adapter", lambda connection: adapter)
    vendor = db.scalar(select(Vendor).where(Vendor.org_id == org.id, Vendor.gstin.like("29%")))

    line_ids = []
    for person, qty in ((team["riya"], "2"), (team["sameer"], "1")):
        login(client, person)
        created = client.post("/requests", json={
            "category_id": str(team["category"].id), "title": "Laptop for a new analyst", "needed_by": "2026-12-20",
            "lines": [{"description": "Laptop 14in, Core i5, 16 GB", "qty": qty, "unit": "pcs"}]}).json()
        client.post(f"/requests/{created['id']}/submit")
        login(client, team["manager"])
        assert client.post(f"/requests/{created['id']}/approvals/1/decision",
                           json={"decision": "approve"}).json()["status"] == "with_buyer"
        line_ids.append(created["lines"][0]["id"])

    login(client, team["buyer"])
    items = {i["item_code"]: i for i in client.get("/ordering/items").json()}
    assert "IT-LAP-14-I5" in items  # the picker offers the ERP's real item codes
    po = client.post("/ordering/pos", json={"vendor_id": str(vendor.id), "lines": [
        {"item_code": "IT-LAP-14-I5", "rate": "78500.00", "request_line_ids": [i]} for i in line_ids]}).json()
    assert po["amount"] == "235500.00" and len(po["lines"]) == 1
    assert client.post(f"/ordering/pos/{po['id']}/submit").json()["status"] == "in_approval"
    login(client, team["finance"])
    approved = client.post(f"/ordering/pos/{po['id']}/approvals/1/decision", json={"decision": "approve"})
    assert approved.json()["status"] == "approved", approved.text
    return approved.json()


def _row(db, po_id) -> ErpOutbox:
    db.expire_all()
    return db.scalar(select(ErpOutbox).where(ErpOutbox.order_po_id == po_id))


def test_one_erp_draft_po_for_two_requests_even_when_the_reply_is_lost(client, db, monkeypatch, team):
    case = CASES["erpnext"]
    adapter = case.build(lambda inner: SavedThenTimedOut(inner, case.is_po_write))
    po = _approved_po(client, db, monkeypatch, team, adapter)
    assert _row(db, po["id"]).state == "PENDING"

    drain_with_retries(db)

    row = _row(db, po["id"])
    assert row.state == "CONFIRMED" and row.attempts == 1
    assert case.count(adapter)["pos"] == 1
    assert adapter.find_po(row.idempotency_key) == row.erp_doc_name

    login(client, team["buyer"])
    preview = client.get(f"/ordering/pos/{po['id']}/vendor-message").json()
    assert row.erp_doc_name in preview["subject"] and row.erp_doc_name in preview["body"]
    sent = client.post(f"/ordering/pos/{po['id']}/send", json={"to": "orders@kaveri.example"})
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    retry = client.post(f"/erp-outbox/{row.id}/retry").json()
    assert "no duplicate created" in retry["message"] and case.count(adapter)["pos"] == 1


def test_submitting_the_draft_in_the_erp_links_it_to_the_orrfin_po(client, db, monkeypatch, team):
    case = CASES["erpnext"]
    adapter = case.build(lambda inner: inner)
    po = _approved_po(client, db, monkeypatch, team, adapter)
    drain_with_retries(db)
    row = _row(db, po["id"])

    case.submit_po(adapter, row.erp_doc_name)  # what a person does inside the ERP
    pull_from_erp(db, team["org"].id, adapter)
    db.commit()

    mirrored = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == team["org"].id,
                                                     PurchaseOrder.order_po_id == po["id"]))
    assert mirrored is not None and mirrored.origin == "orrfin"
    assert mirrored.grand_total >= Decimal("235500.00")
