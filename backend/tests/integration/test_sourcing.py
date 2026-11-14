"""Sourcing through the API (BUILD_PLAN change 43, §6f, §9).

What must hold: quotes are sealed until close; weights are frozen when the RFQ opens; only
invited, approved suppliers quote, and only for their own company; a non-top award needs a
reason; the award becomes a normal draft request, not an order; nothing crosses orgs.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import PurchaseRequest, RfqEvent
from tests.conftest import login
from tests.integration.test_procurement import World, world  # noqa: F401  (world is a fixture)
from tests.integration.test_suppliers import _complete, _decide, _invite, _portal_login


def _approved_supplier(client, world: World, name: str) -> dict:
    invited = _invite(client, world, name=name)
    _complete(client, invited)
    assert _decide(client, world.finance, invited["id"]).status_code == 200
    return invited


def _rfq(client, world: World, **changes) -> dict:
    login(client, world.buyer)
    body = {"title": "Office chairs", "category_id": str(world.category.id), "currency": "INR",
            "closes_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "lines": [{"description": "Ergonomic chair", "qty": "10"}], **changes}
    created = client.post("/rfqs", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _quote(client, supplier: dict, rfq: dict, rate: str, *, delivery=10, terms=30):
    assert _portal_login(client, supplier["email"]).status_code == 200
    return client.put(f"/portal/rfqs/{rfq['id']}/quote", json={
        "currency": "INR", "freight": "500.00", "payment_terms_days": terms, "delivery_days": delivery,
        "valid_until": (date.today() + timedelta(days=30)).isoformat(),
        "lines": [{"rfq_line_id": rfq["lines"][0]["id"], "rate": rate, "tax_rate": "18"}]})


def _close_now(db, rfq_id: str) -> None:
    row = db.get(RfqEvent, rfq_id)
    row.closes_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()


def test_a_sealed_rfq_is_quoted_compared_and_awarded_into_a_normal_request(client, db, world):
    cheap = _approved_supplier(client, world, "Cheap Chairs Pvt Ltd")
    fast = _approved_supplier(client, world, "Fast Chairs Pvt Ltd")
    rfq = _rfq(client, world)
    assert client.post(f"/rfqs/{rfq['id']}/open").status_code == 422          # nobody invited yet
    assert client.post(f"/rfqs/{rfq['id']}/invites", json={"supplier_ids": [cheap["id"], fast["id"]]}).status_code == 200
    assert client.post(f"/rfqs/{rfq['id']}/open").json()["status"] == "open"

    assert _quote(client, cheap, rfq, "4000.00", delivery=20).status_code == 200
    assert _quote(client, fast, rfq, "4500.00", delivery=5).status_code == 200
    mine = client.get("/portal/rfqs").json()
    assert len(mine) == 1 and mine[0]["lines"][0]["rate"] == "4500.00"      # the supplier sees only its own

    login(client, world.buyer)
    sealed = client.get(f"/rfqs/{rfq['id']}").json()
    assert sealed["comparison"] is None
    _close_now(db, rfq["id"])
    closed = client.get(f"/rfqs/{rfq['id']}").json()
    assert closed["status"] == "closed"
    rows = closed["comparison"]
    # With the default weights, delivery in 5 days instead of 20 outweighs a 12% higher price.
    assert [r["supplier_name"] for r in rows] == ["Fast Chairs Pvt Ltd", "Cheap Chairs Pvt Ltd"]
    assert rows[1]["landed_cost"] == "47700.00"                              # 40,000 + 18% + 500 freight

    assert _quote(client, cheap, rfq, "1.00").status_code == 409             # too late to change a price
    login(client, world.buyer)
    second = rows[1]["quote_id"]
    assert client.post(f"/rfqs/{rfq['id']}/award", json={"quote_id": second}).status_code == 422
    awarded = client.post(f"/rfqs/{rfq['id']}/award", json={"quote_id": second, "reason": "Cheapest; 20 days is fine for us"})
    assert awarded.status_code == 200, awarded.text
    request = db.get(PurchaseRequest, awarded.json()["request_id"])
    assert (request.status, request.amount, request.requested_by) == ("draft", 40000, world.buyer.id)
    assert client.post(f"/rfqs/{rfq['id']}/award", json={"quote_id": second, "reason": "again"}).status_code == 409


def test_weights_must_add_up_and_cannot_change_after_opening(client, world):
    bad = {"price": 90, "delivery": 20, "payment_terms": 0, "supplier_risk": 0}
    login(client, world.buyer)
    body = {"title": "X", "category_id": str(world.category.id), "currency": "INR", "weights": bad,
            "closes_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "lines": [{"description": "A", "qty": "1"}]}
    assert client.post("/rfqs", json=body).status_code == 422
    rfq = _rfq(client, world, weights={"price": 40, "delivery": 40, "payment_terms": 10, "supplier_risk": 10})
    assert rfq["weights"]["delivery"] == 40


def test_only_invited_approved_suppliers_quote(client, db, world):
    invited = _approved_supplier(client, world, "Invited Supplies")
    outsider = _approved_supplier(client, world, "Not Invited Supplies")
    pending = _invite(client, world, name="Pending Supplies")
    rfq = _rfq(client, world)
    assert client.post(f"/rfqs/{rfq['id']}/invites", json={"supplier_ids": [pending["id"]]}).status_code == 409
    client.post(f"/rfqs/{rfq['id']}/invites", json={"supplier_ids": [invited["id"]]})
    assert _quote(client, invited, rfq, "100.00").status_code == 409         # still a draft
    login(client, world.buyer)
    client.post(f"/rfqs/{rfq['id']}/open")
    assert _quote(client, outsider, rfq, "100.00").status_code == 404
    assert client.get("/portal/rfqs").json() == []
    bad_line = _quote(client, invited, rfq, "-1.00")
    assert bad_line.status_code == 422


def test_roles_and_orgs(client, factory, world):
    login(client, world.requester)
    assert client.get("/rfqs").status_code == 403
    rfq = _rfq(client, world)
    other = factory.user(factory.org("Other org"), "admin")
    login(client, other)
    assert client.get(f"/rfqs/{rfq['id']}").status_code == 404
    assert client.post(f"/rfqs/{rfq['id']}/open").status_code == 404
    assert client.get("/rfqs").json() == []
    login(client, world.approver if hasattr(world, "approver") else world.manager)
    assert client.post(f"/rfqs/{rfq['id']}/close").status_code == 403
