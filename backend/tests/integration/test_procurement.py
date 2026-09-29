"""Intake-to-procure rules (BUILD_PLAN §9 routing, approval chain, segregation of duties; §11 M2 acceptance tests).

Each test builds its own org through the API, the way users drive it, so the rules
are checked where they are enforced: on the server.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import ApprovalPolicy, AuditEvent, Category, PurchaseRequest, Vendor
from app.modules.audit.service import verify_chain
from app.seed_demo import POLICIES
from tests.conftest import login


@dataclass
class World:
    org: object
    requester: object
    manager: object
    buyer: object
    finance: object
    admin: object
    category: object
    orphan_category: object
    vendor: object


@pytest.fixture
def world(db, factory) -> World:
    from datetime import UTC, datetime

    org = factory.org()
    manager = factory.user(org, "approver", limit="500000", name="Manager")
    requester = factory.user(org, "requester", manager=manager, name="Requester")
    buyer = factory.user(org, "buyer", name="Buyer")
    finance = factory.user(org, "finance", limit="5000000", name="Finance")
    admin = factory.user(org, "admin", limit="10000000", name="Admin")
    category = Category(org_id=org.id, name="IT hardware", buyer_id=buyer.id)
    orphan = Category(org_id=org.id, name="Unowned category", buyer_id=None)
    vendor = Vendor(org_id=org.id, erp_ref="Kaveri IT", name="Kaveri IT Solutions LLP",
                    gstin="29AAKFK3310P1Z5", state_code="29", erp_modified=datetime.now(UTC))
    db.add_all([category, orphan, vendor])
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()
    return World(org, requester, manager, buyer, finance, admin, category, orphan, vendor)


def _new_request(client, world, *, amount: str = "240000.00", category=None, as_user=None) -> dict:
    """Create and submit a one-line request for `amount` (qty 2 x amount/2)."""
    login(client, as_user or world.requester)
    rate = str(Decimal(amount) / 2)
    created = client.post("/requests", json={
        "category_id": str((category or world.category).id),
        "title": "Laptops for the new analysts",
        "justification": "Two analysts join on 1 October.",
        "cost_center": "FIN-OPS",
        "needed_by": "2026-10-15",
        "lines": [{"description": "Laptop 14in, Core i5, 16 GB", "qty": "2", "est_rate": rate}],
    })
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    submitted = client.post(f"/requests/{request_id}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _complete_and_send(client, world, request: dict, *, buyer=None) -> dict:
    login(client, buyer or world.buyer)
    lines = [{"id": line["id"], "item_code": "IT-LAP-14-I5", "est_rate": line["est_rate"], "qty": line["qty"]}
             for line in request["lines"]]
    updated = client.patch(f"/requests/{request['id']}/buyer",
                           json={"vendor_id": str(world.vendor.id), "lines": lines})
    assert updated.status_code == 200, updated.text
    sent = client.post(f"/requests/{request['id']}/send-for-approval")
    assert sent.status_code == 200, sent.text
    return sent.json()


def _decide(client, user, request_id: str, step: int, decision: str = "approve", reason: str | None = None):
    login(client, user)
    return client.post(f"/requests/{request_id}/approvals/{step}/decision",
                       json={"decision": decision, "reason": reason})


# --- Routing -----------------------------------------------------------------------------------

def test_a_submitted_request_routes_to_its_categorys_buyer(client, world):
    request = _new_request(client, world)

    assert request["status"] == "with_buyer"
    assert request["assigned_buyer_id"] == str(world.buyer.id)
    login(client, world.buyer)
    queue = client.get("/requests", params={"scope": "buyer_queue"}).json()
    assert [r["id"] for r in queue] == [request["id"]]


def test_a_category_with_no_buyer_goes_to_the_admin_queue(client, world):
    request = _new_request(client, world, category=world.orphan_category)

    assert request["status"] == "submitted" and request["assigned_buyer_id"] is None
    login(client, world.admin)
    assert [r["id"] for r in client.get("/requests", params={"scope": "admin_queue"}).json()] == [request["id"]]
    assigned = client.post(f"/requests/{request['id']}/assign", json={"buyer_id": str(world.buyer.id)})
    assert assigned.status_code == 200 and assigned.json()["status"] == "with_buyer"


def test_amount_is_the_decimal_sum_of_the_lines(client, world):
    login(client, world.requester)
    created = client.post("/requests", json={
        "category_id": str(world.category.id), "title": "Mixed", "justification": "x",
        "cost_center": "OPS", "lines": [
            {"description": "Cable", "qty": "3", "est_rate": "0.10"},
            {"description": "Adapter", "qty": "1.5", "est_rate": "0.20"},
        ],
    }).json()

    assert created["amount"] == "0.60"


# --- Approval chain from policy ----------------------------------------------------------------

@pytest.mark.parametrize("amount, steps", [
    ("40000.00", ["manager"]),
    ("200000.00", ["manager", "finance"]),
    ("600000.00", ["manager", "finance", "admin"]),
])
def test_the_chain_length_follows_the_amount_tier(client, world, amount, steps):
    request = _complete_and_send(client, world, _new_request(client, world, amount=amount))

    assert request["status"] == "in_approval"
    assert [s["required_role"] for s in request["current_steps"]] == steps


def test_a_laptop_request_walks_to_approved_and_is_ready_for_po(client, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))

    assert _decide(client, world.manager, request["id"], 1).status_code == 200
    final = _decide(client, world.finance, request["id"], 2)

    assert final.status_code == 200
    assert final.json()["status"] == "approved"
    assert final.json()["ready_for_po"] is True


# --- Segregation of duties ---------------------------------------------------------------------

def test_requester_cannot_approve_their_own_request(client, world, factory):
    # The requester holds the finance role, so only the own-request rule can stop them.
    finance_requester = factory.user(world.org, "finance", limit="5000000", manager=world.manager)
    request = _complete_and_send(client, world, _new_request(client, world, as_user=finance_requester))
    _decide(client, world.manager, request["id"], 1)

    response = _decide(client, finance_requester, request["id"], 2)

    assert response.status_code == 403
    assert "own request" in response.json()["detail"]


def test_the_buyer_who_completed_a_request_cannot_approve_it(client, db, world, factory):
    # This buyer owns the category AND is the requester's manager, so only the buyer rule can stop them.
    buyer_manager = factory.user(world.org, "buyer", limit="500000")
    requester = factory.user(world.org, "requester", manager=buyer_manager)
    their_category = Category(org_id=world.org.id, name="Office supplies", buyer_id=buyer_manager.id)
    db.add(their_category)
    db.commit()
    request = _complete_and_send(
        client, world, _new_request(client, world, as_user=requester, category=their_category),
        buyer=buyer_manager)

    response = _decide(client, buyer_manager, request["id"], 1)

    assert response.status_code == 403
    assert "completed" in response.json()["detail"]


def test_one_person_cannot_approve_two_steps(client, world, factory):
    # Manager of the requester AND holder of the finance role: eligible for both steps.
    finance_manager = factory.user(world.org, "finance", limit="5000000")
    requester = factory.user(world.org, "requester", manager=finance_manager)
    request = _complete_and_send(client, world, _new_request(client, world, as_user=requester))
    assert _decide(client, finance_manager, request["id"], 1).status_code == 200

    response = _decide(client, finance_manager, request["id"], 2)

    assert response.status_code == 403
    assert "already approved" in response.json()["detail"]


def test_steps_must_be_approved_in_order(client, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="200000.00"))

    response = _decide(client, world.finance, request["id"], 2)

    assert response.status_code == 409


def test_an_approval_above_the_approvers_limit_is_refused(client, world):
    # ₹6,00,000 is above the manager's ₹5,00,000 limit.
    request = _complete_and_send(client, world, _new_request(client, world, amount="600000.00"))

    response = _decide(client, world.manager, request["id"], 1)

    assert response.status_code == 403
    assert "limit" in response.json()["detail"]


def test_an_approver_must_hold_the_steps_role(client, world, factory):
    other_manager = factory.user(world.org, "approver", limit="500000")
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))

    # Right role name, but not this requester's manager.
    assert _decide(client, other_manager, request["id"], 1).status_code == 403


# --- Changes, rejection and return -------------------------------------------------------------

def test_changing_the_amount_restarts_the_chain(client, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="200000.00"))
    assert _decide(client, world.manager, request["id"], 1).status_code == 200

    login(client, world.buyer)
    line = request["lines"][0]
    changed = client.patch(f"/requests/{request['id']}/buyer", json={
        "vendor_id": str(world.vendor.id),
        "lines": [{"id": line["id"], "item_code": "IT-LAP-14-I5", "qty": line["qty"], "est_rate": "105000.00"}],
    })

    body = changed.json()
    assert changed.status_code == 200
    assert body["amount"] == "210000.00"
    assert body["approval_round"] == 2
    assert [s["decision"] for s in body["current_steps"]] == [None, None]
    # The old step-1 approval no longer counts: step 2 is out of order again.
    assert _decide(client, world.finance, request["id"], 2).status_code == 409


def test_reject_and_return_need_a_reason(client, world):
    request = _complete_and_send(client, world, _new_request(client, world))

    assert _decide(client, world.manager, request["id"], 1, "reject").status_code == 422
    assert _decide(client, world.manager, request["id"], 1, "return", reason="  ").status_code == 422


def test_reject_ends_the_request(client, world):
    request = _complete_and_send(client, world, _new_request(client, world))

    rejected = _decide(client, world.manager, request["id"], 1, "reject", reason="Not budgeted this quarter")

    assert rejected.json()["status"] == "rejected"
    assert _decide(client, world.finance, request["id"], 2).status_code == 409


def test_return_sends_it_back_to_the_requester_who_can_resubmit(client, world):
    request = _complete_and_send(client, world, _new_request(client, world))
    returned = _decide(client, world.manager, request["id"], 1, "return", reason="Add the second quote")
    assert returned.json()["status"] == "returned"

    login(client, world.requester)
    edited = client.patch(f"/requests/{request['id']}", json={"justification": "Quote 2 attached."})
    resubmitted = client.post(f"/requests/{request['id']}/submit")

    assert edited.status_code == 200
    assert resubmitted.json()["status"] == "with_buyer"


# --- Audit and tenancy -------------------------------------------------------------------------

def test_every_state_change_writes_exactly_one_audit_event(client, db, world):
    request = _complete_and_send(client, world, _new_request(client, world))
    _decide(client, world.manager, request["id"], 1)
    _decide(client, world.finance, request["id"], 2)

    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == request["id"])
                         .order_by(AuditEvent.seq)).all()

    assert actions == ["created", "submitted", "buyer_updated", "sent_for_approval",
                       "step_approved", "approved"]
    assert verify_chain(db, request["id"])


def test_a_refused_action_writes_no_audit_event(client, db, world):
    request = _complete_and_send(client, world, _new_request(client, world))
    before = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == request["id"])).all()

    _decide(client, world.requester, request["id"], 1)

    after = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == request["id"])).all()
    assert len(after) == len(before)


def test_requests_are_invisible_to_other_orgs_and_to_other_requesters(client, world, factory):
    request = _new_request(client, world)
    stranger = factory.user(factory.org("Other org"), "admin", limit="1")
    colleague = factory.user(world.org, "requester", manager=world.manager)

    login(client, stranger)
    assert client.get(f"/requests/{request['id']}").status_code == 404
    login(client, colleague)
    assert client.get(f"/requests/{request['id']}").status_code == 404


def test_the_approvals_inbox_shows_only_steps_the_user_can_act_on(client, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="200000.00"))

    login(client, world.manager)
    manager_inbox = client.get("/requests", params={"scope": "approvals"}).json()
    login(client, world.finance)
    finance_inbox = client.get("/requests", params={"scope": "approvals"}).json()

    assert [r["id"] for r in manager_inbox] == [request["id"]]
    assert finance_inbox == []  # finance's step comes after the manager's


def test_the_database_amount_is_numeric(db, client, world):
    request = _new_request(client, world, amount="240000.00")

    stored = db.scalar(select(PurchaseRequest.amount).where(PurchaseRequest.id == request["id"]))

    assert stored == Decimal("240000.00") and isinstance(stored, Decimal)
