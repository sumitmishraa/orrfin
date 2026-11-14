"""Legal entities and exchange rates through the API, and the UAE regime reaching the match (§5, §6d, §9).

What must hold: only an admin changes an entity and only finance or an admin enters a rate;
a regime never sits on the wrong country; a rate is never overwritten or future-dated; nothing
leaks across orgs; and an invoice billed to a UAE entity is checked with the UAE rules.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app import job_handlers  # noqa: F401  (registers the match job)
from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import AuditEvent, Document, Invoice, InvoiceLine, MatchResult, PurchaseOrder
from app.modules.entities import service
from app.modules.invoices.match_job import start_match
from app.modules.sync.service import pull_from_erp
from tests.conftest import login

UAE = {"name": "Orrfin Gulf FZ-LLC", "country": "AE", "base_currency": "AED", "tax_regime": "ae_vat",
       "tax_id": "100987654300003"}
INDIA = {"name": "Orrfin India Pvt Ltd", "country": "IN", "base_currency": "INR", "tax_regime": "in_gst",
         "tax_id": "27AAACO1234F1Z5"}


def _org_with(factory, *roles: str):
    org = factory.org()
    return org, [factory.user(org, role, limit="5000000") for role in roles]


def test_an_org_starts_with_one_default_indian_entity(client, factory):
    _, (requester,) = _org_with(factory, "requester")
    login(client, requester)
    entities = client.get("/entities").json()
    assert [(e["tax_regime"], e["base_currency"], e["is_default"]) for e in entities] == [("in_gst", "INR", True)]
    assert len(client.get("/entities").json()) == 1  # reading twice does not make a second one


def test_only_an_admin_can_create_or_change_an_entity(client, db, factory):
    org, (admin, finance, requester) = _org_with(factory, "admin", "finance", "requester")
    for user in (finance, requester):
        login(client, user)
        assert client.post("/entities", json=UAE).status_code == 403
    login(client, admin)
    created = client.post("/entities", json=UAE)
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == uuid.UUID(entity_id)))
    assert (event.action, event.actor_id) == ("created", admin.id)
    login(client, finance)
    assert client.put(f"/entities/{entity_id}", json={**UAE, "name": "Renamed"}).status_code == 403
    assert client.post(f"/entities/{entity_id}/make-default").status_code == 403


def test_a_regime_cannot_sit_on_the_wrong_country_or_tax_number(client, factory):
    _, (admin,) = _org_with(factory, "admin")
    login(client, admin)
    for bad in (
        {**UAE, "country": "IN"},                       # UAE VAT on an Indian company
        {**INDIA, "country": "AE"},                     # GST on a UAE company
        {**UAE, "tax_id": "27AAACO1234F1Z5"},           # a GSTIN where a TRN belongs
        {**INDIA, "tax_id": "100987654300003"},         # a TRN where a GSTIN belongs
        {**INDIA, "state_code": "29"},                  # state code that is not the GSTIN's
        {**UAE, "state_code": "27"},                    # a GST state on a UAE entity
        {**UAE, "base_currency": "GBP"},
        {**UAE, "tax_regime": "us_sales_tax"},
    ):
        response = client.post("/entities", json=bad)
        assert response.status_code == 422, (bad, response.text)
    assert client.post("/entities", json=INDIA).json()["state_code"] == "27"
    assert client.post("/entities", json=INDIA).status_code == 409  # same name twice


def test_one_org_cannot_reach_another_orgs_entity_or_connection(client, db, factory):
    _, (admin_a,) = _org_with(factory, "admin")
    org_b, (admin_b,) = _org_with(factory, "admin")
    login(client, admin_b)
    theirs = client.post("/entities", json=UAE).json()["id"]
    pull_from_erp(db, org_b.id, FakeErpnextAdapter(REPO_ROOT / "seed" / "erpnext"))
    db.commit()
    their_connection = db.scalar(select(PurchaseOrder.erp_connection_id).where(PurchaseOrder.org_id == org_b.id))

    login(client, admin_a)
    assert theirs not in [e["id"] for e in client.get("/entities").json()]
    assert client.put(f"/entities/{theirs}", json=UAE).status_code == 404
    assert client.post(f"/entities/{theirs}/make-default").status_code == 404
    assert client.get(f"/entities/{theirs}/members").status_code == 404
    assert client.put(f"/entities/{theirs}/members", json={"user_ids": []}).status_code == 404
    linked = client.post("/entities", json={**UAE, "erp_connection_id": str(their_connection)})
    assert linked.status_code == 404
    mine = client.post("/entities", json=UAE).json()["id"]
    assert client.put(f"/entities/{mine}/members", json={"user_ids": [str(admin_b.id)]}).status_code == 404


def test_the_default_entity_is_always_there(client, factory):
    _, (admin,) = _org_with(factory, "admin")
    login(client, admin)
    default = client.get("/entities").json()[0]
    body = {**INDIA, "name": default["name"]}
    assert client.put(f"/entities/{default['id']}", json={**body, "active": False}).status_code == 409
    gulf = client.post("/entities", json=UAE).json()
    assert client.post(f"/entities/{gulf['id']}/make-default").json()["is_default"] is True
    assert [e["id"] for e in client.get("/entities").json() if e["is_default"]] == [gulf["id"]]
    # The old default may now be switched off; the new one may not.
    assert client.put(f"/entities/{default['id']}", json={**body, "active": False}).status_code == 200
    assert client.put(f"/entities/{gulf['id']}", json={**UAE, "active": False}).status_code == 409
    assert client.post(f"/entities/{default['id']}/make-default").status_code == 409  # switched off


def test_exchange_rates_are_typed_in_by_finance_and_never_overwritten(client, db, factory):
    org, (finance, requester) = _org_with(factory, "finance", "requester")
    today = date.today()
    rate = {"base_currency": "AED", "quote_currency": "INR", "rate": "22.63500000", "as_of": today.isoformat()}
    login(client, requester)
    assert client.post("/entities/fx-rates", json=rate).status_code == 403
    login(client, finance)
    assert client.post("/entities/fx-rates", json=rate).status_code == 201
    assert client.post("/entities/fx-rates", json={**rate, "rate": "25"}).status_code == 409
    for bad in (
        {**rate, "rate": 22.6},                                              # a JSON number could be a float
        {**rate, "rate": "0"}, {**rate, "rate": "-1"}, {**rate, "rate": "1e3"},
        {**rate, "quote_currency": "AED"},                                   # the same currency twice
        {**rate, "quote_currency": "GBP"},
        {**rate, "as_of": (today + timedelta(days=1)).isoformat()},          # tomorrow's rate is not known
    ):
        assert client.post("/entities/fx-rates", json=bad).status_code == 422, bad
    listed = client.get("/entities/fx-rates").json()
    assert [(r["rate"], r["entered_by_name"]) for r in listed] == [("22.63500000", finance.full_name)]

    # The rate used for a day is the latest one entered on or before it, never a later one.
    earlier = today - timedelta(days=10)
    client.post("/entities/fx-rates", json={**rate, "rate": "22.10", "as_of": earlier.isoformat()})
    assert service.rate_on(db, org.id, "AED", "INR", today - timedelta(days=3)).rate == Decimal("22.10")
    assert service.rate_on(db, org.id, "AED", "INR", today).rate == Decimal("22.635")
    assert service.rate_on(db, org.id, "AED", "INR", earlier - timedelta(days=1)) is None
    assert service.rate_on(db, org.id, "INR", "AED", today) is None  # the reverse pair is not invented

    _, (other_finance,) = _org_with(factory, "finance")
    login(client, other_finance)
    assert client.get("/entities/fx-rates").json() == []


def test_an_invoice_billed_to_a_uae_entity_is_checked_with_the_uae_rules(client, db, factory):
    org, (admin, finance) = _org_with(factory, "admin", "finance")
    pull_from_erp(db, org.id, FakeErpnextAdapter(REPO_ROOT / "seed" / "erpnext"))
    db.commit()
    login(client, admin)
    gulf = client.post("/entities", json=UAE).json()
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == org.id).limit(1))

    document = Document(org_id=org.id, s3_key="test/uae.pdf", sha256="a" * 64, filename="uae.pdf",
                        content_type="application/pdf", size_bytes=10, uploaded_by=finance.id)
    db.add(document)
    db.flush()
    invoice = Invoice(org_id=org.id, document_id=document.id, status="confirmed", vendor_name="Gulf Supplies LLC",
                      vendor_gstin="100234567800003", buyer_gstin=UAE["tax_id"], invoice_no="DXB-1",
                      invoice_no_norm="DXB1", invoice_date=date(2026, 11, 10), fiscal_year="2026-27",
                      po_reference=po.erp_ref, currency="AED", subtotal=Decimal("1000.00"), cgst=Decimal("0"),
                      sgst=Decimal("0"), igst=Decimal("0"), vat=Decimal("50.00"), total=Decimal("1050.00"),
                      confirmed_by=finance.id, confirmed_at=datetime.now(UTC))
    db.add(invoice)
    db.flush()
    db.add(InvoiceLine(org_id=org.id, invoice_id=invoice.id, line_no=1, description="Chairs", item_code="NOPE",
                       qty=Decimal("10"), rate=Decimal("100.00"), amount=Decimal("1000.00")))
    start_match(db, invoice, finance.id)
    db.commit()
    drain(db)

    db.expire_all()
    result = db.scalar(select(MatchResult).where(MatchResult.invoice_id == invoice.id))
    by_rule = {r["rule"]: r["code"] for r in result.rule_results}
    assert result.inputs_snapshot["tax_regime"] == "ae_vat"
    assert by_rule["trn"] == "OK"                       # the TRN is judged as a TRN, not as a bad GSTIN
    assert by_rule["tax_type"] == "OK"                  # VAT only
    assert by_rule["currency"] == "CURRENCY_MISMATCH"   # the PO is in rupees; nothing is converted
    assert "gstin" not in by_rule
    assert db.get(Invoice, invoice.id).entity_id == uuid.UUID(gulf["id"])

    login(client, finance)
    detail = client.get(f"/invoices/{invoice.id}").json()
    assert (detail["tax_regime"], detail["entity_name"], detail["vat"]) == ("ae_vat", UAE["name"], "50.00")
    # A VAT bill is never pushed through the GST-only draft-bill contract.
    assert "UAE VAT" in service_note(db, invoice.id)


def service_note(db, invoice_id) -> str:
    from app.modules.erp_outbox.service import bill_unavailable_reason

    return bill_unavailable_reason(db, db.get(Invoice, invoice_id)) or ""
