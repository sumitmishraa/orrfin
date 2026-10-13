"""§8 "Draft Purchase Orders" exactly once, for every write-capable ERP (PROMPTS Step 15).

- The PO is saved, then the reply is lost → the retry looks it up (find_po) → exactly one draft PO, row
  CONFIRMED, request `po_drafted`.
- A validation error → FAILED, shown on the request.
- The final approval and the outbox row are atomic: if the transaction fails, neither exists.
- A person submits the draft in the ERP → the next sync links it (origin orrfin) → request `po_open`.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.models import ApprovalPolicy, Category, ErpOutbox, PurchaseOrder, PurchaseRequest, Vendor
from app.modules.erp_outbox import po as po_module
from app.modules.erp_outbox import service as outbox
from app.modules.sync.service import pull_from_erp
from app.seed_demo import POLICIES
from tests.conftest import login
from tests.failure.erp_write_cases import CASES, Rejects, SavedThenTimedOut, drain_with_retries


@pytest.fixture(params=sorted(CASES), ids=sorted(CASES))
def case(request):
    return CASES[request.param]


@pytest.fixture
def team(db, factory):
    org = factory.org()
    manager = factory.user(org, "approver", limit="500000", name="Manager")
    requester = factory.user(org, "requester", manager=manager, name="Requester")
    buyer = factory.user(org, "buyer", name="Buyer")
    finance = factory.user(org, "finance", limit="5000000", name="Finance")
    category = Category(org_id=org.id, name="IT hardware", buyer_id=buyer.id)
    db.add(category)
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()
    return {"org": org, "manager": manager, "requester": requester, "buyer": buyer, "finance": finance,
            "category": category}


def _approve_request(client, db, monkeypatch, team, adapter) -> str:
    """Mirror the ERP, then request → buyer picks the ERP vendor → manager and finance approve."""
    org = team["org"]
    pull_from_erp(db, org.id, adapter)
    db.commit()
    monkeypatch.setattr(outbox, "get_adapter", lambda connection: adapter)
    monkeypatch.setattr(po_module, "get_adapter", lambda connection: adapter)
    vendor = db.scalar(select(Vendor).where(Vendor.org_id == org.id, Vendor.gstin.like("29%")))

    login(client, team["requester"])
    created = client.post("/requests", json={
        "category_id": str(team["category"].id), "title": "Laptops for two analysts", "justification": "New joiners.",
        "cost_center": "FIN-OPS", "needed_by": "2026-10-20",
        "lines": [{"description": "Laptop 14in, Core i5, 16 GB", "qty": "2", "est_rate": "78500.00"}]}).json()
    client.post(f"/requests/{created['id']}/submit")
    login(client, team["buyer"])
    lines = [{"id": line["id"], "item_code": "IT-LAP-14-I5", "est_rate": "78500.00", "qty": "2"}
             for line in created["lines"]]
    assert client.patch(f"/requests/{created['id']}/buyer",
                        json={"vendor_id": str(vendor.id), "lines": lines}).status_code == 200
    assert client.post(f"/requests/{created['id']}/send-for-approval").status_code == 200
    for step, user in ((1, team["manager"]), (2, team["finance"])):
        login(client, user)
        response = client.post(f"/requests/{created['id']}/approvals/{step}/decision", json={"decision": "approve"})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    return created["id"]


def _row(db, request_id) -> ErpOutbox | None:
    db.expire_all()
    return db.scalar(select(ErpOutbox).where(ErpOutbox.request_id == request_id))


def test_saved_then_timed_out_ends_with_exactly_one_draft_po(client, db, monkeypatch, team, case):
    adapter = case.build(lambda inner: SavedThenTimedOut(inner, case.is_po_write))
    request_id = _approve_request(client, db, monkeypatch, team, adapter)
    assert _row(db, request_id).state == "PENDING"

    drain_with_retries(db)

    row = _row(db, request_id)
    assert row.state == "CONFIRMED" and row.attempts == (2 if case.multi_call_write else 1)
    assert case.count(adapter)["pos"] == 1
    assert adapter.find_po(row.idempotency_key) == row.erp_doc_name
    detail = client.get(f"/requests/{request_id}").json()
    assert detail["status"] == "po_drafted" and detail["po_sync"]["erp_doc_name"] == row.erp_doc_name
    retry = client.post(f"/erp-outbox/{row.id}/retry").json()
    assert "no duplicate created" in retry["message"] and case.count(adapter)["pos"] == 1


def test_validation_error_is_failed_and_shown_on_the_request(client, db, monkeypatch, team, case):
    adapter = case.build(lambda inner: Rejects(inner, case.is_po_write))
    request_id = _approve_request(client, db, monkeypatch, team, adapter)
    drain_with_retries(db)

    detail = client.get(f"/requests/{request_id}").json()
    assert detail["status"] == "approved"
    assert detail["po_sync"]["state"] == "FAILED" and detail["po_sync"]["last_error"]
    assert case.count(adapter)["pos"] == 0


def test_the_final_approval_and_its_outbox_row_are_atomic(client, db, monkeypatch, team):
    adapter = CASES["erpnext"].build(lambda inner: inner)

    def broken_enqueue(*args, **kwargs):
        raise RuntimeError("database went away mid-approval")

    monkeypatch.setattr(po_module, "enqueue", broken_enqueue)
    with pytest.raises(RuntimeError):
        _approve_request(client, db, monkeypatch, team, adapter)
    db.expire_all()
    request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.org_id == team["org"].id))
    assert request.status == "in_approval"  # the approval rolled back with the outbox row
    assert db.scalar(select(ErpOutbox).where(ErpOutbox.request_id == request.id)) is None


def test_submitting_the_draft_in_the_erp_then_syncing_opens_the_po(client, db, monkeypatch, team, case):
    if case.submit_po is None:
        pytest.skip(f"{case.name} drafts can't be submitted by a test")
    adapter = case.build(lambda inner: inner)
    request_id = _approve_request(client, db, monkeypatch, team, adapter)
    drain_with_retries(db)
    row = _row(db, request_id)
    assert row.state == "CONFIRMED"

    case.submit_po(adapter, row.erp_doc_name)  # what a person does inside the ERP
    pull_from_erp(db, team["org"].id, adapter)
    db.commit()

    # Some ERPs give the submitted PO a new number (SAP Business One adds a draft as a new document), so the
    # link that counts is the one Orrfin keeps: the request id found through the PO's Orrfin key.
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == team["org"].id,
                                               PurchaseOrder.request_id == request_id))
    assert po is not None and po.origin == "orrfin"
    assert po.grand_total >= Decimal("157000.00")
    assert client.get(f"/requests/{request_id}").json()["status"] == "po_open"
