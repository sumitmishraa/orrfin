"""Connectors page end to end (BUILD_PLAN §4, §5 erp_connections, §9; PROMPTS Step 12; ADR 0006).

The live ERPNext connector is exercised for real (encryption, tests, jobs, audit, sync) with only its
transport swapped: calls go to a blank simulated Frappe site that insists on the exact
`token key:secret` the admin saved. So these tests prove the whole "paste keys → Test connection →
Prepare demo data → Make active → Sync" path the founder will click, without an ERP account.
"""

import dataclasses
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import job_handlers  # noqa: F401  (registers erp_pull and erp_prepare)
from app.adapters import registry
from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.jobs import drain
from app.models import AuditEvent, ErpConnection, Job, PurchaseOrder, Vendor
from app.security.outbound import ErpHttp
from tests.conftest import login

API_KEY, API_SECRET = "key-abc123", "secret-xyz-0042-very-private"
SITE = "https://orrfin-demo.frappe.cloud"


@pytest.fixture
def live_erpnext(monkeypatch):
    """Route the live ERPNext connector to one blank simulated site for the whole test."""
    server = FakeFrappeServer(None, SimStore(None), empty=True, required_token=f"{API_KEY}:{API_SECRET}")
    real_live = registry.CATALOGUE["erpnext"].live

    def live(connection, values):
        adapter = real_live(connection, values)  # the real factory: URL check, auth header, redaction
        http: ErpHttp = adapter.http
        swapped = ErpHttp(base_url=http.base_url, headers=dict(http.client.headers), secrets=http.secrets,
                          transport=httpx.MockTransport(server), erp_name="ERPNext")
        return ErpnextAdapter(swapped, label="live", company=adapter.company)

    monkeypatch.setitem(registry.CATALOGUE, "erpnext", dataclasses.replace(registry.CATALOGUE["erpnext"], live=live))
    return server


@pytest.fixture
def admin(factory):
    org = factory.org()
    return factory.user(org, "admin"), factory.user(org, "finance"), org


def _card(client, system="erpnext"):
    return next(c for c in client.get("/connectors").json() if c["system"] == system)


def _save(client, secret=API_SECRET):
    return client.put("/connectors/erpnext/credentials",
                      json={"values": {"url": SITE, "api_key": API_KEY, "api_secret": secret}})


def _everything_stored(db, org_id) -> str:
    rows = [json.dumps(e.payload) for e in db.scalars(select(AuditEvent).where(AuditEvent.org_id == org_id))]
    rows += [json.dumps(j.payload) + str(j.last_error) + json.dumps(j.result) for j in
             db.scalars(select(Job).where(Job.org_id == org_id))]
    rows += [str(c.last_error) + json.dumps(c.last_check) + str(c.credentials_encrypted)
             for c in db.scalars(select(ErpConnection).where(ErpConnection.org_id == org_id))]
    return "\n".join(rows)


def test_only_admins_manage_connectors(client, admin):
    _, finance, _ = admin
    login(client, finance)
    assert client.get("/connectors").status_code == 403
    assert _save(client).status_code == 403
    assert client.get("/connectors/active").status_code == 200  # everyone may see which ERP is active


def test_catalogue_lists_all_nineteen_erps_with_honest_labels(client, admin):
    user, _, _ = admin
    login(client, user)
    cards = client.get("/connectors").json()
    assert len(cards) == 19  # 11 from Steps 12-20, 8 from Step 36 (all simulated)
    step_36 = [c for c in cards if c["system"] in ("quickbooks_online", "xero", "sage_intacct", "sage_50", "acumatica",
                                                     "focus_x", "marg", "tally_uae")]
    assert len(step_36) == 8 and all(c["live_label"] == "simulated" for c in step_36)
    erpnext = next(c for c in cards if c["system"] == "erpnext")
    assert erpnext["built"] and erpnext["simulated"]["is_active"] and erpnext["simulated"]["label"] == "simulated"
    assert {c["live_label"] for c in cards} == {"live", "sandbox", "simulated"}
    assert erpnext["capabilities"]["draft_bill_means"]


def test_saved_secret_is_never_shown_stored_in_clear_or_audited(client, db, admin, live_erpnext):
    user, _, org = admin
    login(client, user)
    response = _save(client)
    assert response.status_code == 200, response.text
    assert API_SECRET not in response.text
    assert response.json()["fields"]["api_secret"]["hint"].endswith("vate")
    assert API_SECRET not in client.get("/connectors").text
    check = client.post(f"/connectors/connections/{response.json()['id']}/test").json()
    assert check["ok"], check
    assert API_SECRET not in _everything_stored(db, org.id)
    saved = db.scalar(select(AuditEvent).where(AuditEvent.org_id == org.id, AuditEvent.action == "erp_credentials_saved"))
    assert saved.payload["fields_set"] == ["api_key", "api_secret", "url"]


def test_blank_secret_on_resave_keeps_the_stored_one(client, admin, live_erpnext):
    user, _, _ = admin
    login(client, user)
    _save(client)
    response = client.put("/connectors/erpnext/credentials",
                          json={"values": {"url": SITE, "api_key": API_KEY, "api_secret": ""}})
    assert response.status_code == 200
    assert client.post(f"/connectors/connections/{response.json()['id']}/test").json()["ok"]


@pytest.mark.parametrize("url", ["http://orrfin-demo.frappe.cloud", "https://192.168.1.20", "https://localhost"])
def test_unsafe_site_addresses_are_refused(client, admin, url):
    user, _, _ = admin
    login(client, user)
    response = client.put("/connectors/erpnext/credentials",
                          json={"values": {"url": url, "api_key": API_KEY, "api_secret": API_SECRET}})
    assert response.status_code == 422


def test_wrong_secret_fails_the_test_and_blocks_activation(client, db, admin, live_erpnext):
    user, _, org = admin
    login(client, user)
    live = _save(client, secret="wrong-secret-value-123").json()
    check = client.post(f"/connectors/connections/{live['id']}/test").json()
    assert not check["ok"]
    assert "credentials" in _card(client)["live"]["last_error"]
    assert "wrong-secret-value-123" not in _everything_stored(db, org.id)
    assert client.post(f"/connectors/connections/{live['id']}/activate").status_code == 409


def test_prepare_activate_and_sync_a_live_erpnext(client, db, admin, live_erpnext):
    user, _, org = admin
    login(client, user)
    live = _save(client).json()
    assert client.post(f"/connectors/connections/{live['id']}/test").json()["ok"]

    job = client.post(f"/connectors/connections/{live['id']}/prepare")
    assert job.status_code == 202
    drain(db)
    db.expire_all()
    prepared = db.get(Job, job.json()["id"])
    assert prepared.status == "done", prepared.last_error
    assert prepared.result["created"]["purchase orders"] == 8
    # Prepare is idempotent: the second run creates nothing.
    client.post(f"/connectors/connections/{live['id']}/prepare")
    drain(db)

    assert client.post(f"/connectors/connections/{live['id']}/activate").status_code == 200
    assert client.get("/connectors/active").json()["label"] == "live"
    client.post("/sync/erp")
    drain(db)
    pos = client.get("/purchase-orders").json()
    assert len(pos) == 8 and {p["po_number"] for p in pos} == {f"PUR-ORD-2026-{n:05d}" for n in range(1, 9)}

    activated = db.scalars(select(AuditEvent).where(AuditEvent.org_id == org.id,
                                                    AuditEvent.action == "erp_connection_activated")).all()
    assert any(e.payload.get("previous") == "erpnext/simulated" for e in activated)


def test_two_connections_with_the_same_refs_do_not_collide_and_resync_is_stable(client, db, admin, live_erpnext):
    user, _, org = admin
    login(client, user)
    client.post("/sync/erp")  # simulated ERPNext (active by default)
    drain(db)
    live = _save(client).json()
    client.post(f"/connectors/connections/{live['id']}/test")
    client.post(f"/connectors/connections/{live['id']}/prepare")
    drain(db)
    client.post(f"/connectors/connections/{live['id']}/activate")
    for _ in range(2):
        client.post("/sync/erp")
        drain(db)

    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.org_id == org.id))

    assert count(PurchaseOrder) == 16 and count(Vendor) == 10  # 8 + 8: same PO numbers, two ERPs
    names = db.scalars(select(PurchaseOrder.erp_ref).where(PurchaseOrder.org_id == org.id)).all()
    assert names.count("PUR-ORD-2026-00001") == 2
    assert len(client.get("/purchase-orders").json()) == 8  # the list shows the active ERP only

    simulated = _card(client)["simulated"]
    client.post(f"/connectors/connections/{simulated['id']}/activate")
    client.post("/sync/erp")
    drain(db)
    assert count(PurchaseOrder) == 16


def test_disconnect_forgets_keys_and_falls_back_to_simulated(client, db, admin, live_erpnext):
    user, _, _ = admin
    login(client, user)
    live = _save(client).json()
    client.post(f"/connectors/connections/{live['id']}/test")
    client.post(f"/connectors/connections/{live['id']}/activate")
    response = client.delete("/connectors/erpnext/credentials")
    assert response.status_code == 200 and response.json()["fields"]["api_secret"]["set"] is False
    assert client.get("/connectors/active").json()["mode"] == "simulated"
    db.expire_all()
    row = db.get(ErpConnection, live["id"])
    assert row.credentials_encrypted is None and not row.is_active


def test_unbuilt_connectors_cannot_be_activated(client, admin):
    user, _, _ = admin
    login(client, user)
    unbuilt = [c for c in client.get("/connectors").json() if not c["built"]]
    if not unbuilt:
        pytest.skip("every connector is built")
    response = client.post(f"/connectors/connections/{unbuilt[0]['simulated']['id']}/activate")
    assert response.status_code == 409 and f"Step {unbuilt[0]['step']}" in response.json()["detail"]
