"""Need-first intake and Orrfin POs (Step 42, ADR 0012; BUILD_PLAN §8, §9).

The order of work a real company follows: the employee states a need (no vendor, price optional), their
manager approves it, procurement puts approved needs on one PO per vendor (merging the same item), the
PO is approved by amount (Finance above ₹50,000), the ERP draft is written, and the PO is "sent" to the
vendor (simulated email). Each test builds its own org through the API, the way users drive it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    ApprovalPolicy,
    AuditEvent,
    Category,
    ErpOutbox,
    Notification,
    OrderPo,
    Vendor,
    VendorMessage,
)
from app.modules.audit.service import verify_chain
from app.modules.connectors.service import active_connection
from app.seed_demo import POLICIES
from tests.conftest import login

ITEM = "IT-LAP-14-I5"


@dataclass
class World:
    org: object
    manager: object
    riya: object
    sameer: object
    loner: object
    buyer: object
    finance: object
    admin: object
    category: object
    vendor: object


def _world(db, factory, *, flow: str = "need_first") -> World:
    org = factory.org()
    org.intake_flow = flow
    manager = factory.user(org, "approver", limit="500000", name="Neha GM")
    riya = factory.user(org, "requester", manager=manager, name="Riya")
    sameer = factory.user(org, "requester", manager=manager, name="Sameer")
    loner = factory.user(org, "requester", name="No Manager")
    buyer = factory.user(org, "buyer", name="Arjun Procurement")
    finance = factory.user(org, "finance", limit="5000000", name="Vikram Finance")
    admin = factory.user(org, "admin", limit="10000000", name="Anita Admin")
    category = Category(org_id=org.id, name="IT hardware", buyer_id=buyer.id)
    vendor = Vendor(org_id=org.id, erp_connection_id=active_connection(db, org.id).id, erp_ref="Kaveri IT",
                    name="Kaveri IT Solutions LLP", gstin="29AAKFK3310P1Z5", state_code="29",
                    erp_modified=datetime.now(UTC))
    db.add_all([category, vendor])
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()
    return World(org, manager, riya, sameer, loner, buyer, finance, admin, category, vendor)


@pytest.fixture
def world(db, factory) -> World:
    return _world(db, factory)


def _need(client, world, user, *, qty: str = "2", description: str = "Laptop 14in, Core i5, 16 GB",
          submit: bool = True, **extra) -> dict:
    """An employee's need: what and how many. No vendor, no price."""
    login(client, user)
    created = client.post("/requests", json={
        "category_id": str(world.category.id), "title": f"{qty} x {description}", "justification": "New joiners.",
        "cost_center": "IT-OPS", "needed_by": "2026-12-15",
        "lines": [{"description": description, "qty": qty, "unit": "pcs"}], **extra})
    assert created.status_code == 201, created.text
    if not submit:
        return created.json()
    submitted = client.post(f"/requests/{created.json()['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _decide_request(client, user, request_id, step=1, decision="approve", reason=None):
    login(client, user)
    return client.post(f"/requests/{request_id}/approvals/{step}/decision", json={"decision": decision, "reason": reason})


def _approved_need(client, world, user, **kwargs) -> dict:
    need = _need(client, world, user, **kwargs)
    approved = _decide_request(client, world.manager, need["id"])
    assert approved.status_code == 200, approved.text
    return approved.json()


def _create_po(client, world, needs: list[dict], *, rate: str, as_user=None):
    """One PO line per need, all with the same item code and rate (the service merges them)."""
    login(client, as_user or world.buyer)
    return client.post("/ordering/pos", json={
        "vendor_id": str(world.vendor.id),
        "lines": [{"item_code": ITEM, "rate": rate, "request_line_ids": [need["lines"][0]["id"]]} for need in needs]})


def _po_with_amount(client, world, amount: str) -> dict:
    need = _approved_need(client, world, world.riya, qty="2")
    created = _create_po(client, world, [need], rate=str(Decimal(amount) / 2))
    assert created.status_code == 201, created.text
    return created.json()


def _submit_po(client, world, po) -> dict:
    login(client, world.buyer)
    submitted = client.post(f"/ordering/pos/{po['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _decide_po(client, user, po_id, step=1, decision="approve", reason=None):
    login(client, user)
    return client.post(f"/ordering/pos/{po_id}/approvals/{step}/decision", json={"decision": decision, "reason": reason})


# --- The need ----------------------------------------------------------------------------------------------

def test_a_need_goes_to_the_requesters_manager_first(client, world):
    need = _need(client, world, world.riya)

    assert need["status"] == "in_approval" and need["intake_flow"] == "need_first"
    assert [s["required_role"] for s in need["current_steps"]] == ["manager"]
    assert need["amount"] == "0.00" and need["vendor_id"] is None  # the employee chose neither
    assert _decide_request(client, world.riya, need["id"]).status_code == 403
    assert _decide_request(client, world.buyer, need["id"]).status_code == 403

    approved = _decide_request(client, world.manager, need["id"])
    assert approved.status_code == 200
    assert approved.json()["status"] == "with_buyer"
    assert approved.json()["waiting_on"].startswith("Procurement")
    login(client, world.buyer)
    needs = client.get("/ordering/needs").json()
    assert [n["request_id"] for n in needs] == [need["id"]]
    assert needs[0]["qty"] == "2.000" and needs[0]["unit"] == "pcs" and needs[0]["requester_name"] == "Riya"


def test_a_requester_without_a_manager_goes_to_an_admin(client, world):
    need = _need(client, world, world.loner)

    assert [s["required_role"] for s in need["current_steps"]] == ["admin"]
    assert _decide_request(client, world.manager, need["id"]).status_code == 403
    assert _decide_request(client, world.admin, need["id"]).json()["status"] == "with_buyer"


def test_the_buyer_cannot_price_a_need_on_the_request_itself(client, world):
    need = _approved_need(client, world, world.riya)
    login(client, world.buyer)

    priced = client.patch(f"/requests/{need['id']}/buyer", json={
        "vendor_id": str(world.vendor.id),
        "lines": [{"id": need["lines"][0]["id"], "item_code": ITEM, "qty": "2", "est_rate": "1000"}]})
    assert priced.status_code == 409
    assert client.get(f"/requests/{need['id']}").json()["allowed"]["buyer_edit"] is False


def test_a_need_entered_for_an_employee_is_submitted_by_the_employee(client, world, db):
    message = "Hi Neha, need 2 laptops for the new joiners by 15 Dec. Thanks, Riya"
    entered = _need(client, world, world.manager, submit=False, source_channel="whatsapp",
                    source_message=message, requested_for_id=str(world.riya.id))

    assert entered["requested_by"] == str(world.riya.id) and entered["entered_by_name"] == "Neha GM"
    assert entered["source_channel"] == "whatsapp" and entered["source_message"] == message
    assert client.post(f"/requests/{entered['id']}/submit").status_code == 403  # Neha typed it; Riya asks
    assert db.scalar(select(Notification).where(Notification.user_id == world.riya.id,
                                                Notification.kind == "request_entered_for_you")) is not None

    login(client, world.riya)
    assert client.post(f"/requests/{entered['id']}/submit").json()["status"] == "in_approval"
    assert _decide_request(client, world.manager, entered["id"]).json()["status"] == "with_buyer"


def test_a_requester_cannot_enter_a_need_for_someone_else(client, world):
    login(client, world.riya)
    response = client.post("/requests", json={
        "category_id": str(world.category.id), "title": "Chair", "requested_for_id": str(world.sameer.id),
        "lines": [{"description": "Chair", "qty": "1"}]})
    assert response.status_code == 403


def test_a_pasted_message_must_be_kept(client, world):
    login(client, world.riya)
    response = client.post("/requests", json={
        "category_id": str(world.category.id), "title": "Chair", "source_channel": "email",
        "lines": [{"description": "Chair", "qty": "1"}]})
    assert response.status_code == 422


# --- Building the PO -------------------------------------------------------------------------------------------

def test_two_needs_for_the_same_item_merge_into_one_po_line(client, world):
    riya = _approved_need(client, world, world.riya, qty="2")
    sameer = _approved_need(client, world, world.sameer, qty="1")

    created = _create_po(client, world, [riya, sameer], rate="78500.00")

    assert created.status_code == 201, created.text
    po = created.json()
    assert po["status"] == "draft" and len(po["lines"]) == 1
    line = po["lines"][0]
    assert line["qty"] == "3.000" and line["amount"] == "235500.00" and po["amount"] == "235500.00"
    assert sorted(s["requester_name"] for s in line["sources"]) == ["Riya", "Sameer"]
    assert po["reference"] == f"PO-{po['number']:04d} (PR-{riya['number']:04d}, PR-{sameer['number']:04d})"
    assert po["chain_preview"] == ["finance"]
    assert client.get("/ordering/needs").json() == []
    for need in (riya, sameer):
        detail = client.get(f"/requests/{need['id']}").json()
        assert detail["status"] == "po_drafted"
        assert detail["lines"][0]["placement"]["po_number"] == f"PO-{po['number']:04d}"


def test_a_need_cannot_go_on_two_purchase_orders(client, world):
    need = _approved_need(client, world, world.riya)
    assert _create_po(client, world, [need], rate="1000.00").status_code == 201

    again = _create_po(client, world, [need], rate="1000.00")
    assert again.status_code == 409


def test_a_need_must_be_approved_before_it_goes_on_a_po(client, world):
    waiting = _need(client, world, world.riya)  # still with the manager

    assert _create_po(client, world, [waiting], rate="1000.00").status_code == 409


def test_only_procurement_or_an_admin_builds_a_po(client, world):
    need = _approved_need(client, world, world.riya)

    assert _create_po(client, world, [need], rate="1000.00", as_user=world.finance).status_code == 403
    assert _create_po(client, world, [need], rate="1000.00", as_user=world.riya).status_code == 403


# --- Approving the PO --------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("amount", "steps"), [
    ("40000.00", []),
    ("55000.00", ["finance"]),
    ("600000.00", ["finance", "admin"]),
])
def test_the_po_chain_is_the_amount_tier_without_the_manager(client, world, db, amount, steps):
    po = _submit_po(client, world, _po_with_amount(client, world, amount))

    assert [s["required_role"] for s in po["steps"]] == steps
    if not steps:
        assert po["status"] == "approved"
        row = db.scalar(select(ErpOutbox).where(ErpOutbox.order_po_id == po["id"]))
        assert row is not None and row.state == "PENDING" and row.request_id is None
    else:
        assert po["status"] == "in_approval"


def test_the_person_who_built_the_po_cannot_approve_it(client, world):
    po = _submit_po(client, world, _po_with_amount(client, world, "600000.00"))

    assert _decide_po(client, world.buyer, po["id"]).status_code == 403
    assert _decide_po(client, world.admin, po["id"], step=1).status_code == 403  # step 1 needs finance
    assert _decide_po(client, world.finance, po["id"], step=2).status_code == 409  # steps go in order
    approved = _decide_po(client, world.finance, po["id"], step=1)
    assert approved.status_code == 200 and approved.json()["status"] == "in_approval"
    final = _decide_po(client, world.admin, po["id"], step=2)
    assert final.status_code == 200 and final.json()["status"] == "approved"


def test_reject_needs_a_reason_and_frees_the_needs(client, world):
    need = _approved_need(client, world, world.riya)
    po = _submit_po(client, world, _create_po(client, world, [need], rate="30000.00").json())

    assert _decide_po(client, world.finance, po["id"], decision="reject").status_code == 422
    rejected = _decide_po(client, world.finance, po["id"], decision="reject", reason="Price is too high")
    assert rejected.json()["status"] == "rejected"
    login(client, world.buyer)
    assert [n["request_id"] for n in client.get("/ordering/needs").json()] == [need["id"]]
    assert client.get(f"/requests/{need['id']}").json()["status"] == "with_buyer"


def test_cancelling_a_draft_po_frees_the_needs(client, world):
    need = _approved_need(client, world, world.riya)
    po = _create_po(client, world, [need], rate="1000.00").json()

    cancelled = client.post(f"/ordering/pos/{po['id']}/cancel", json={"reason": "Wrong vendor"})
    assert cancelled.json()["status"] == "cancelled"
    assert _create_po(client, world, [need], rate="900.00").status_code == 201


# --- Sending to the vendor ---------------------------------------------------------------------------------------

def test_a_po_in_approval_cannot_be_sent(client, world):
    po = _submit_po(client, world, _po_with_amount(client, world, "60000.00"))  # above ₹50,000 → finance
    assert po["status"] == "in_approval" and po["allowed"]["send"] is False
    login(client, world.buyer)
    assert client.post(f"/ordering/pos/{po['id']}/send", json={"to": "sales@kaveri.example"}).status_code == 409


def test_an_empty_po_is_refused(client, world):
    login(client, world.buyer)
    assert client.post("/ordering/pos", json={"vendor_id": str(world.vendor.id), "lines": []}).status_code == 422


@pytest.fixture
def approved_po(client, world, db):
    """Riya (2) + Sameer (1) laptops at ₹15,000 = ₹45,000: within procurement's limit, approved on submit."""
    riya = _approved_need(client, world, world.riya, qty="2")
    sameer = _approved_need(client, world, world.sameer, qty="1")
    po = _submit_po(client, world, _create_po(client, world, [riya, sameer], rate="15000.00").json())
    assert po["status"] == "approved"
    return po, riya, sameer


def test_a_po_cannot_be_sent_until_the_erp_confirms_its_draft(client, world, db, approved_po):
    po, _, _ = approved_po
    login(client, world.buyer)

    blocked = client.post(f"/ordering/pos/{po['id']}/send", json={"to": "sales@kaveri.example"})
    assert blocked.status_code == 409 and "Waiting for the ERP" in blocked.json()["detail"]


def test_sending_records_the_email_and_marks_the_needs_ordered(client, world, db, approved_po):
    po, riya, sameer = approved_po
    row = db.scalar(select(ErpOutbox).where(ErpOutbox.order_po_id == po["id"]))
    row.state, row.erp_doc_name = "CONFIRMED", "PUR-ORD-2026-00042"  # what the worker does (failure tests)
    db.commit()
    login(client, world.buyer)

    preview = client.get(f"/ordering/pos/{po['id']}/vendor-message").json()
    assert "PUR-ORD-2026-00042" in preview["subject"]
    assert "Please find attached our purchase order" in preview["body"] and "3 pcs" in preview["body"]
    assert client.post(f"/ordering/pos/{po['id']}/send", json={"to": "not-an-email"}).status_code == 422

    sent = client.post(f"/ordering/pos/{po['id']}/send", json={"to": "sales@kaveri.example", "note": "Deliver to Pune."})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent" and sent.json()["messages"][0]["to"] == "sales@kaveri.example"
    message = db.scalar(select(VendorMessage).where(VendorMessage.order_po_id == po["id"]))
    assert message.channel == "email" and "Deliver to Pune." in message.body and message.attachment_name.endswith(".pdf")
    for need in (riya, sameer):
        assert client.get(f"/requests/{need['id']}").json()["status"] == "po_open"
    assert db.scalar(select(Notification).where(Notification.user_id == world.riya.id,
                                                Notification.kind == "request_ordered")) is not None
    assert verify_chain(db, po["id"])
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == po["id"]).order_by(AuditEvent.seq)).all()
    assert actions == ["created", "approved", "sent_to_vendor"]
    pdf = client.get(f"/documents/order-po/{po['id']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


# --- Who sees what -------------------------------------------------------------------------------------------------

def test_requesters_and_other_orgs_cannot_see_orders(client, world, db, factory, approved_po):
    po, _, _ = approved_po
    login(client, world.riya)
    assert client.get("/ordering/pos").status_code == 403
    assert client.get(f"/ordering/pos/{po['id']}").status_code == 404
    assert client.get(f"/documents/order-po/{po['id']}").status_code == 404

    other = _world(db, factory)
    login(client, other.admin)
    assert client.get(f"/ordering/pos/{po['id']}").status_code == 404
    assert client.get("/ordering/pos").json() == []
    assert client.get("/ordering/needs").json() == []


def test_a_buyer_first_org_does_not_use_orders(client, db, factory):
    world = _world(db, factory, flow="buyer_first")
    need = _need(client, world, world.riya)
    assert need["status"] == "with_buyer"  # the old order: the buyer prices it before approval

    login(client, world.buyer)
    assert client.get("/ordering/needs").json() == []
    response = client.post("/ordering/pos", json={"vendor_id": str(world.vendor.id), "lines": [
        {"item_code": ITEM, "rate": "1000", "request_line_ids": [need["lines"][0]["id"]]}]})
    assert response.status_code == 409


def test_order_po_numbers_are_per_org(client, world, db):
    first = _po_with_amount(client, world, "1000.00")
    second = _po_with_amount(client, world, "2000.00")
    assert (first["number"], second["number"]) == (1, 2)
    assert db.scalar(select(OrderPo.amount).where(OrderPo.id == second["id"])) == Decimal("2000.00")
