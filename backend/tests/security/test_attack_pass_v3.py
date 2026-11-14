"""Attack pass over the v3.0 products (BUILD_PLAN change 50, §9; PROMPTS Step 38).

Each test is an attack an outsider, a supplier, an employee or another org could try, written so it
fails if the hole ever opens: two-step sign-in replay, row-level security, mass assignment, SQL and
prompt injection through new inputs, file-name tricks, and security headers on the new routes.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.auth import totp
from app.db import SessionLocal, scope_to_org
from app.models import Category, LegalEntity, Supplier, SupplierDocument, User
from tests.conftest import TEST_PASSWORD, login
from tests.integration.test_procurement import world  # noqa: F401  (fixture)
from tests.integration.test_suppliers import _invite, _join, _upload


# --- Two-step sign-in ------------------------------------------------------------------------------------

def test_two_step_sign_in_needs_a_fresh_code_every_time(client, db, factory):
    org = factory.org()
    user = factory.user(org, "finance")
    login(client, user)
    secret = client.post("/auth/mfa/setup").json()["secret"]
    assert client.post("/auth/mfa/enable", json={"code": "000000"}).status_code == 422
    code = totp.code_at(secret, totp.current_step())
    assert client.post("/auth/mfa/enable", json={"code": code}).json()["mfa_enabled"] is True

    client.cookies.clear()
    no_code = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert no_code.status_code == 401 and no_code.headers["x-orrfin-mfa"] == "required"
    replay = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD, "code": code})
    assert replay.status_code == 401                                      # the enable code cannot be reused
    next_code = totp.code_at(secret, totp.current_step() + 1)
    assert client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD,
                                            "code": next_code}).status_code == 200
    assert client.post("/auth/mfa/disable", json={"code": next_code}).status_code == 422   # used already
    db.expire_all()
    assert db.get(User, user.id).mfa_secret_encrypted.startswith("gAAAA")  # stored encrypted, not in clear


def test_totp_matches_the_rfc_6238_test_vector():
    # RFC 6238 appendix B, SHA-1: the ASCII secret "12345678901234567890" at T = 59 s gives 94287082.
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30) == "287082"   # the same value, cut to six digits
    assert totp.verify(secret, "287082", last_step=None, now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None


# --- Row-level security -------------------------------------------------------------------------------------

def test_the_database_hides_and_refuses_another_orgs_rows(world, factory):
    other = factory.org("Other org")
    with SessionLocal() as session:
        theirs = Category(org_id=other.id, name="Their secret category")
        session.add(theirs)
        session.commit()
        their_id = theirs.id
    with SessionLocal() as scoped:
        scope_to_org(scoped, world.org.id)
        assert scoped.get(Category, their_id) is None                     # invisible, even by primary key
        assert scoped.scalar(select(Category).where(Category.id == their_id)) is None
        assert scoped.scalar(select(Category).where(Category.org_id == world.org.id)) is not None
        scoped.add(LegalEntity(org_id=other.id, name="Planted", country="IN", base_currency="INR", tax_regime="in_gst"))
        with pytest.raises(DBAPIError):                                   # and it cannot write into another org
            scoped.commit()


# --- Mass assignment ------------------------------------------------------------------------------------

def test_extra_fields_in_a_request_body_are_ignored(client, db, world):
    login(client, world.buyer)
    created = client.post("/suppliers/invites", json={
        "legal_name": "Sneaky Ltd", "country": "IN", "category": "goods", "contact_name": "S",
        "contact_email": f"s-{uuid.uuid4().hex[:6]}@x.test", "status": "approved", "invited_by": str(world.admin.id),
        "on_hold": False, "vendor_id": str(world.vendor.id)})
    supplier = db.get(Supplier, uuid.UUID(created.json()["id"]))
    assert (supplier.status, supplier.invited_by, supplier.vendor_id) == ("invited", world.buyer.id, None)

    login(client, world.admin)
    entity = client.post("/entities", json={"name": "Gulf", "country": "AE", "base_currency": "AED",
                                            "tax_regime": "ae_vat", "tax_id": "100987654300003", "is_default": True})
    assert entity.json()["is_default"] is False


# --- Injection through the new inputs ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["' OR '1'='1", "x'; DROP TABLE purchase_requests; --", "%' UNION SELECT * FROM users --"])
def test_sql_shaped_text_is_only_ever_text(client, world, text):
    login(client, world.admin)
    key = client.post("/integrations/api-keys", json={"name": "k"}).json()["key"]
    client.cookies.clear()
    reply = client.post("/mcp", headers={"Authorization": f"Bearer {key}"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "find_requests", "arguments": {"text": text}}}).json()
    assert reply["result"]["isError"] is False and "PR-" not in reply["result"]["content"][0]["text"]


def test_a_supplier_file_name_never_becomes_a_path(client, db, world):
    invited = _invite(client, world)
    _join(client, invited)
    uploaded = client.post("/portal/documents", data={"kind": "pan"},
                           files={"file": ("../../../../etc/passwd", b"%PDF-1.4 x", "application/pdf")})
    assert uploaded.status_code == 201
    stored = db.scalar(select(SupplierDocument).where(SupplierDocument.supplier_id == uuid.UUID(invited["id"])))
    assert ".." not in stored.s3_key and stored.s3_key.endswith(".pdf")
    assert _upload(client, "pan", data=b"%PDF-1.4 <script>", content_type="image/svg+xml").status_code == 422


# --- Headers on the new routes -----------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/rfqs", "/contracts", "/cards", "/spend", "/app-studio", "/agents", "/suppliers"])
def test_new_routes_send_the_browser_protections(client, world, path):
    login(client, world.admin)
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["cache-control"] == "no-store"
