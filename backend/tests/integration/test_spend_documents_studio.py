"""Spend insights, generated PDFs and App Studio (BUILD_PLAN change 49, §11 M15).

What must hold: spend totals equal the records they come from, per currency, with committed /
invoiced / paid kept apart; exports cannot smuggle spreadsheet formulas; each PDF opens and shows its
record; App Studio records follow their form, their approver role and segregation of duties.
"""

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pypdf import PdfReader
from sqlalchemy import select

from app.models import Invoice, PurchaseOrder
from app.modules.spend.service import as_csv
from tests.conftest import login
from tests.integration.test_invoice_review import _decide as decide_invoice
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_procurement import world  # noqa: F401  (fixture)


def _text(pdf: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_spend_equals_its_records_per_currency(client, db, team):
    invoice_id = _matched(client, db, team.uploader, "01-clean-match")
    assert decide_invoice(client, team.reviewer, invoice_id).status_code == 200
    invoice = db.get(Invoice, invoice_id)
    login(client, team.reviewer)
    cube = client.get("/spend", params={"group_by": "vendor"}).json()
    invoiced = sum(Decimal(r["invoiced"]) for r in cube["rows"] if r["currency"] == "INR")
    committed = sum(Decimal(r["committed"]) for r in cube["rows"] if r["currency"] == "INR")
    assert invoiced == invoice.total
    assert committed == sum(p.grand_total for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.org_id == team.org.id)))
    assert all(Decimal(r["paid"]) == 0 for r in cube["rows"])           # nothing paid: never mixed with invoiced
    assert client.get("/spend", params={"group_by": "favourite_colour"}).status_code == 422
    assert client.get("/spend/export.csv", params={"group_by": "month"}).text.startswith("month,Currency")
    assert "Spend by category" in _text(client.get("/spend/export.pdf", params={"group_by": "category"}).content)


def test_a_csv_export_cannot_carry_a_formula():
    data = {"group_by": "vendor", "rows": [{"group": "=HYPERLINK(\"http://evil\")", "currency": "INR",
                                            "committed": Decimal("1"), "invoiced": Decimal("0"), "paid": Decimal("0")}]}
    assert as_csv(data).splitlines()[1].startswith("\"'=HYPERLINK")


def test_po_and_audit_pdfs_open_and_respect_roles(client, db, team, factory):
    invoice_id = _matched(client, db, team.uploader, "01-clean-match")
    decide_invoice(client, team.reviewer, invoice_id)
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == team.org.id).limit(1))
    login(client, team.reviewer)
    assert (po.po_number or po.erp_ref) in _text(client.get(f"/documents/po/{po.id}").content)
    pack = client.get(f"/documents/audit/{invoice_id}")
    assert pack.status_code == 200 and "intact" in _text(pack.content)
    requester = factory.user(team.org, "requester")
    login(client, requester)
    assert client.get(f"/documents/po/{po.id}").status_code == 403
    assert client.get(f"/documents/audit/{invoice_id}").status_code == 403
    login(client, factory.user(factory.org("Other org"), "admin"))
    assert client.get(f"/documents/po/{po.id}").status_code == 404
    assert client.get(f"/documents/audit/{invoice_id}").status_code == 404


def test_an_rfq_pdf_shows_its_lines_and_weights(client, world):
    login(client, world.buyer)
    rfq = client.post("/rfqs", json={"title": "Desk lamps", "category_id": str(world.category.id), "currency": "INR",
                                     "closes_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                                     "lines": [{"description": "LED desk lamp", "qty": "12"}]}).json()
    text = _text(client.get(f"/documents/rfq/{rfq['id']}").content)
    assert "Desk lamps" in text and "LED desk lamp" in text and "price 60" in text


APP = {"key": "laptop_loan", "name": "Laptop loan", "approver_role": "approver", "list_columns": ["model", "days"],
       "fields": [{"key": "model", "label": "Model", "kind": "choice", "required": True, "options": ["13 inch", "15 inch"]},
                  {"key": "days", "label": "Days", "kind": "number", "required": True}]}


def test_app_studio_records_follow_their_form_role_and_sod(client, world, factory):
    login(client, world.buyer)
    assert client.post("/app-studio", json=APP).status_code == 403
    login(client, world.admin)
    assert client.post("/app-studio", json={**APP, "list_columns": ["secret"]}).status_code == 422
    assert client.post("/app-studio", json={**APP, "approver_role": "requester"}).status_code == 422
    app = client.post("/app-studio", json=APP).json()

    login(client, world.requester)
    assert client.post(f"/app-studio/{app['id']}/records", json={"values": {"model": "17 inch", "days": "3"}}).status_code == 422
    view = client.post(f"/app-studio/{app['id']}/records", json={"values": {"model": "13 inch", "days": "3"}}).json()
    record = view["records"][0]
    assert record["status"] == "submitted" and record["can_decide"] is False
    decide = f"/app-studio/{app['id']}/records/{record['id']}/decision"
    assert client.post(decide, json={"decision": "approve"}).status_code == 403          # not the approver role
    login(client, world.manager)                                                         # role "approver"
    assert client.post(decide, json={"decision": "reject"}).status_code == 422           # a rejection needs a reason
    assert client.post(decide, json={"decision": "approve"}).json()["records"][0]["status"] == "approved"
    assert client.post(decide, json={"decision": "approve"}).status_code == 409

    own = client.post(f"/app-studio/{app['id']}/records", json={"values": {"model": "15 inch", "days": "1"}}).json()
    mine = next(r for r in own["records"] if r["status"] == "submitted")
    assert client.post(f"/app-studio/{app['id']}/records/{mine['id']}/decision", json={"decision": "approve"}).status_code == 403
    login(client, world.admin)
    assert client.post("/app-studio", json={**APP, "name": "Changed"}).status_code == 409   # questions frozen once used
    login(client, factory.user(factory.org("Other org"), "admin"))
    assert client.get(f"/app-studio/{app['id']}/records").status_code == 404
