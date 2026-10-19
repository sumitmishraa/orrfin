"""Control dashboard and Rules page (BUILD_PLAN v2.3 changes 23–24; PROMPTS Step 21).

Done when: insights numbers are right on a fixed dataset; org A cannot see org B; a non-admin
edit is refused; gapped or overlapping tiers are refused; an in-flight request keeps its chain
while a new request uses the new tier; every edit leaves an audit event.
"""

from decimal import Decimal

from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.models import AuditEvent, RequestApproval
from app.modules.rules.service import tiers_entity_id
from tests.conftest import login
from tests.integration.test_invoice_review import _decide as decide_invoice
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_procurement import _complete_and_send, _decide, _new_request, world  # noqa: F401

ALL_TIME = {"period": "all"}


def _summary(client, user, **params):
    login(client, user)
    response = client.get("/insights/summary", params=params or ALL_TIME)
    assert response.status_code == 200, response.text
    return response.json()


# --- Requests and approvals --------------------------------------------------------------------------

def test_request_numbers_on_a_fixed_dataset(client, world):
    small = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    assert _decide(client, world.manager, small["id"], 1).status_code == 200  # one step: approved
    large = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))
    assert _decide(client, world.manager, large["id"], 1).status_code == 200  # now waits on finance
    _new_request(client, world, amount="1000.00")  # with the buyer

    data = _summary(client, world.finance)
    requests = data["requests"]
    assert requests["open_total"] == 2
    assert requests["open_by_status"]["with_buyer"] == 1 and requests["open_by_status"]["in_approval"] == 1
    assert [(w["step"], w["count"]) for w in requests["waiting_by_step"]] == [("finance", 1)]
    assert requests["approved_count"] == 1
    assert Decimal(requests["approval_hours_average"]) >= 0
    assert [a["approver"] for a in requests["slowest_approvers"]] == ["Manager"]
    assert requests["slowest_approvers"][0]["decisions"] == 2
    # Spend counts only requests whose approval chain finished, by category and cost centre.
    spend = data["spend"]
    assert spend["approved_requests_total"] == "40000.00"
    assert spend["by_category"] == [{"name": "IT hardware", "amount": "40000.00"}]
    assert spend["by_cost_center"] == [{"name": "FIN-OPS", "amount": "40000.00"}]


def test_a_requester_sees_only_their_own_requests_and_no_invoice_data(client, world, factory):
    _new_request(client, world, amount="5000.00")
    other = factory.user(world.org, "requester", manager=world.manager, name="Other requester")
    _new_request(client, world, amount="7000.00", as_user=other)

    mine = _summary(client, world.requester)
    assert mine["requests"]["open_total"] == 1
    assert mine["invoices"] is None and mine["spend"] is None and mine["erp_drafts"] is None
    assert _summary(client, world.finance)["requests"]["open_total"] == 2


def test_org_a_cannot_see_org_b(client, world, factory):
    _new_request(client, world, amount="5000.00")
    other_org = factory.org("Other Org")
    stranger = factory.user(other_org, "admin", limit="1000000")

    data = _summary(client, stranger)
    assert data["requests"]["open_total"] == 0
    assert data["invoices"]["total"] == 0 and data["spend"]["approved_requests_total"] == "0"


def test_period_filter_is_accepted_and_bad_periods_are_refused(client, world):
    login(client, world.finance)
    for period in ("month", "quarter", "all"):
        assert client.get("/insights/summary", params={"period": period}).status_code == 200
    assert client.get("/insights/summary", params={"period": "decade"}).status_code == 422


# --- Invoices ----------------------------------------------------------------------------------------

def test_invoice_numbers_on_a_fixed_dataset(client, db, team):  # noqa: F811
    clean = _matched(client, db, team.uploader, "01-clean-match")
    assert decide_invoice(client, team.reviewer, clean).status_code == 200
    _matched(client, db, team.uploader, "02-price-variance-7pct")  # ₹910 at risk
    _matched(client, db, team.uploader, "03-over-receipt-qty")  # ₹33,800 at risk

    invoices = _summary(client, team.reviewer)["invoices"]
    assert invoices["total"] == 3
    assert invoices["on_hold_count"] == 2
    assert invoices["on_hold_amount_at_risk"] == "34710.00"
    assert invoices["match_attempted"] == 3 and invoices["matched_first_time"] == 1
    assert invoices["first_pass_match_rate"] == "33.3"
    codes = {row["code"] for row in invoices["exceptions_by_code"]}
    assert {"PRICE_VARIANCE", "QTY_EXCEEDS_RECEIPT"} <= codes
    assert invoices["extraction"]["read_by_ai"] == 3


# --- Rules page --------------------------------------------------------------------------------------

NEW_TIERS = {"tiers": [
    {"min_amount": "0.00", "max_amount": "100000.00", "steps": ["manager"]},
    {"min_amount": "100000.01", "max_amount": None, "steps": ["manager", "finance", "admin"]},
]}


def test_everyone_reads_the_rules_but_only_admins_edit(client, world):
    login(client, world.requester)
    rules = client.get("/rules").json()
    assert rules["can_edit"] is False
    assert [t["steps"] for t in rules["approval_tiers"]] == [["manager"], ["manager", "finance"],
                                                              ["manager", "finance", "admin"]]
    assert rules["matching"]["rule_set_version"] and rules["matching"]["tolerances"]["price_pct"] == "0.02"
    assert len(rules["segregation_of_duties"]) >= 6
    assert client.put("/rules/approval-tiers", json=NEW_TIERS).status_code == 403
    login(client, world.finance)
    assert client.put("/rules/approval-tiers", json=NEW_TIERS).status_code == 403
    assert client.patch(f"/rules/categories/{world.category.id}", json={"buyer_id": None}).status_code == 403


def _put_tiers(client, admin, tiers):
    login(client, admin)
    return client.put("/rules/approval-tiers", json={"tiers": tiers})


def test_gapped_overlapping_or_open_middle_tiers_are_refused(client, world):
    cases = {
        "gap": [{"min_amount": "0", "max_amount": "1000.00", "steps": ["manager"]},
                {"min_amount": "2000.00", "max_amount": None, "steps": ["finance"]}],
        "overlap": [{"min_amount": "0", "max_amount": "1000.00", "steps": ["manager"]},
                    {"min_amount": "500.00", "max_amount": None, "steps": ["finance"]}],
        "not from zero": [{"min_amount": "10.00", "max_amount": None, "steps": ["manager"]}],
        "capped last": [{"min_amount": "0", "max_amount": "1000.00", "steps": ["manager"]}],
        "unknown step": [{"min_amount": "0", "max_amount": None, "steps": ["cfo"]}],
        "same step twice": [{"min_amount": "0", "max_amount": None, "steps": ["finance", "finance"]}],
    }
    for name, tiers in cases.items():
        response = _put_tiers(client, world.admin, tiers)
        assert response.status_code == 422, (name, response.text)
    # Nothing changed: the three demo tiers are still the active ones.
    assert len(client.get("/rules").json()["approval_tiers"]) == 3


def test_a_tier_edit_applies_to_new_chains_only_and_is_audited(client, db, world):
    in_flight = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))
    assert [s["required_role"] for s in in_flight["current_steps"]] == ["manager", "finance"]

    response = _put_tiers(client, world.admin, NEW_TIERS["tiers"])
    assert response.status_code == 200, response.text
    assert [t["steps"] for t in response.json()["approval_tiers"]] == [["manager"], ["manager", "finance", "admin"]]

    # The request already in approval keeps its two steps…
    steps = db.scalars(select(RequestApproval.required_role).where(
        RequestApproval.request_id == in_flight["id"]).order_by(RequestApproval.step)).all()
    assert steps == ["manager", "finance"]
    # …while a new request of the same amount gets the new three-step chain.
    fresh = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))
    assert [s["required_role"] for s in fresh["current_steps"]] == ["manager", "finance", "admin"]

    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == tiers_entity_id(world.org.id)))
    assert event.action == "tiers_replaced" and event.actor_id == world.admin.id
    assert len(event.payload["old"]) == 3 and len(event.payload["new"]) == 2


def test_an_admin_changes_a_categorys_buyer_with_an_audit_event(client, db, world, factory):
    new_buyer = factory.user(world.org, "buyer", name="New buyer")
    login(client, world.admin)
    response = client.patch(f"/rules/categories/{world.category.id}", json={"buyer_id": str(new_buyer.id)})
    assert response.status_code == 200, response.text
    row = next(c for c in response.json()["categories"] if c["id"] == str(world.category.id))
    assert row["buyer_name"] == "New buyer"
    # Only a buyer can own a category.
    assert client.patch(f"/rules/categories/{world.category.id}",
                        json={"buyer_id": str(world.finance.id)}).status_code == 422
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == world.category.id))
    assert event.action == "buyer_changed" and event.payload["new_buyer_id"] == str(new_buyer.id)
    # A new request in that category now routes to the new buyer.
    assert _new_request(client, world)["assigned_buyer_id"] == str(new_buyer.id)


def test_another_orgs_category_is_not_found(client, world, factory):
    stranger = factory.user(factory.org("Other Org"), "admin", limit="1")
    login(client, stranger)
    assert client.patch(f"/rules/categories/{world.category.id}", json={"buyer_id": None}).status_code == 404


def test_periods_follow_india_time_and_the_april_march_financial_year():
    from datetime import date

    from app.modules.insights.service import period_start

    # 1 Oct 00:00 IST is 30 Sep 18:30 UTC: Q3 of the financial year (Oct–Dec).
    assert period_start("quarter", date(2026, 11, 18)).isoformat() == "2026-09-30T18:30:00+00:00"
    assert period_start("quarter", date(2027, 2, 5)).isoformat() == "2026-12-31T18:30:00+00:00"  # Q4 = Jan–Mar
    assert period_start("quarter", date(2026, 4, 1)).isoformat() == "2026-03-31T18:30:00+00:00"  # Q1 = Apr–Jun
    assert period_start("month", date(2026, 10, 18)).isoformat() == "2026-09-30T18:30:00+00:00"
    assert period_start("all") is None
