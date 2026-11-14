"""Supplier onboarding and the supplier portal through the API (BUILD_PLAN §9 v3.0, §6e, §11 M10).

What must hold: a supplier session reaches only its own record and no employee route; an
invitation works once; the inviter cannot approve; a block stops approval and a hold needs a
reason; bank details never come back out; a changed bank account goes back to review; the ERP
vendor is linked by the sync, never created by Orrfin.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import AuditEvent, SanctionsEntry, Supplier, SupplierInvite
from app.modules.suppliers import service
from tests.conftest import login
from tests.integration.test_procurement import World, world  # noqa: F401  (world is a fixture)

PDF = b"%PDF-1.4 synthetic certificate"
PASSWORD = "portal-pass-2026!"
ANSWERS = {"data_security_policy": "yes", "related_party": "no", "legal_proceedings": "no"}


def _gstin() -> str:
    """A well-formed, made-up GSTIN, different on every call."""
    digits = f"{uuid.uuid4().int % 10000:04d}"
    return f"27AAAC{'ABCDEFGHJK'[int(digits[0])]}{digits}F1Z5"


def _account() -> str:
    return f"{uuid.uuid4().int % 10**12:012d}"


def _invite(client, world: World, *, by=None, name="Zenith Trading Pvt Ltd", country="IN", category="goods") -> dict:
    login(client, by or world.buyer)
    email = f"contact-{uuid.uuid4().hex[:10]}@supplier.test"
    created = client.post("/suppliers/invites", json={"legal_name": name, "country": country, "category": category,
                                                      "contact_name": "Asha Rao", "contact_email": email})
    assert created.status_code == 201, created.text
    return {**created.json(), "email": email, "token": created.json()["invite_link"].split("token=")[1]}


def _portal_login(client, email: str, password: str = PASSWORD):
    client.cookies.clear()
    return client.post("/portal/login", json={"email": email, "password": password})


def _join(client, invited: dict) -> None:
    client.cookies.clear()
    assert client.post("/portal/invites/accept", json={"token": invited["token"], "password": PASSWORD}).status_code == 204
    assert _portal_login(client, invited["email"]).status_code == 200


def _upload(client, kind: str, data: bytes = PDF, content_type: str = "application/pdf", **form):
    return client.post("/portal/documents", data={"kind": kind, **form},
                       files={"file": (f"{kind}.pdf", data, content_type)})


def _complete(client, invited: dict, *, account: str | None = None, documents=("tax_certificate", "pan", "bank_proof"),
              answers=ANSWERS) -> None:
    """Sign in as the supplier, fill everything in and submit."""
    _join(client, invited)
    assert client.put("/portal/profile", json={"tax_id": _gstin(), "pan": "AAACZ1234F", "answers": answers}).status_code == 200
    bank = client.put("/portal/bank", json={"account_name": "Zenith Trading", "account_number": account or _account(),
                                            "ifsc": "HDFC0001234"})
    assert bank.status_code == 200, bank.text
    for kind in documents:
        assert _upload(client, kind).status_code == 201
    submitted = client.post("/portal/submit")
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted", submitted.text


def _decide(client, user, supplier_id: str, decision: str = "approve", reason: str | None = None):
    login(client, user)
    return client.post(f"/suppliers/{supplier_id}/decision", json={"decision": decision, "reason": reason})


# --- Invitations -----------------------------------------------------------------------------------

def test_who_may_invite_and_that_only_the_tokens_hash_is_kept(client, db, world):
    login(client, world.requester)
    refused = client.post("/suppliers/invites", json={"legal_name": "X", "country": "IN", "category": "goods",
                                                      "contact_name": "Y", "contact_email": "y@supplier.test"})
    assert refused.status_code == 403
    assert client.get("/suppliers").status_code == 403
    invited = _invite(client, world)
    stored = db.scalar(select(SupplierInvite).where(SupplierInvite.supplier_id == uuid.UUID(invited["id"])))
    assert stored.token_hash == service.token_hash(invited["token"]) and invited["token"] != stored.token_hash
    again = client.post("/suppliers/invites", json={"legal_name": "Other", "country": "IN", "category": "goods",
                                                    "contact_name": "Asha", "contact_email": invited["email"].upper()})
    assert again.status_code == 409
    for bad in ({"country": "US"}, {"category": "weapons"}, {"contact_email": "not-an-email"}, {"legal_name": " "}):
        body = {"legal_name": "X", "country": "IN", "category": "goods", "contact_name": "Y",
                "contact_email": "z@supplier.test", **bad}
        assert client.post("/suppliers/invites", json=body).status_code == 422, bad


def test_an_invitation_works_once_and_expires(client, db, world):
    invited = _invite(client, world)
    client.cookies.clear()
    assert client.post("/portal/invites/accept", json={"token": invited["token"], "password": "short"}).status_code == 422
    assert _portal_login(client, invited["email"]).status_code == 401     # no password yet, so no way in
    assert client.post("/portal/invites/accept", json={"token": invited["token"], "password": PASSWORD}).status_code == 204
    reused = client.post("/portal/invites/accept", json={"token": invited["token"], "password": "another-password-1"})
    assert reused.status_code == 422
    assert _portal_login(client, invited["email"], "another-password-1").status_code == 401
    assert client.post("/portal/invites/accept", json={"token": "x" * 43, "password": PASSWORD}).status_code == 422

    late = _invite(client, world)
    row = db.scalar(select(SupplierInvite).where(SupplierInvite.supplier_id == uuid.UUID(late["id"])))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    client.cookies.clear()
    assert client.post("/portal/invites/accept", json={"token": late["token"], "password": PASSWORD}).status_code == 422


# --- The two login realms --------------------------------------------------------------------------

def test_a_supplier_session_reaches_no_employee_route_and_the_reverse(client, world):
    invited = _invite(client, world)
    _join(client, invited)
    assert client.get("/portal/me").json()["legal_name"] == "Zenith Trading Pvt Ltd"
    for path in ("/requests", "/suppliers", f"/suppliers/{invited['id']}", "/invoices", "/auth/me", "/entities",
                 "/integrations/api-keys", "/notifications", "/workflow-definitions"):
        assert client.get(path).status_code == 401, path
    assert client.post(f"/suppliers/{invited['id']}/decision", json={"decision": "approve"}).status_code == 401

    login(client, world.admin)                       # an employee session is not a portal session
    for call in (client.get("/portal/me"), client.post("/portal/submit"),
                 client.put("/portal/bank", json={"account_name": "A", "account_number": "123456789", "ifsc": "HDFC0001234"})):
        assert call.status_code == 401


def test_a_supplier_sees_only_its_own_record(client, world):
    first, second = _invite(client, world, name="First Supplies"), _invite(client, world, name="Second Supplies")
    _join(client, first)
    assert client.put("/portal/profile", json={"tax_id": _gstin(), "pan": "AAACZ1234F", "answers": ANSWERS}).status_code == 200
    _join(client, second)
    mine = client.get("/portal/me").json()
    assert (mine["legal_name"], mine["tax_id"]) == ("Second Supplies", None)
    client.post("/portal/logout")
    assert client.get("/portal/me").status_code == 401


def test_wrong_portal_passwords_lock_the_email(client, world):
    invited = _invite(client, world)
    _join(client, invited)
    for _ in range(5):
        assert _portal_login(client, invited["email"], "wrong-password-123").status_code == 401
    assert _portal_login(client, invited["email"]).status_code == 429


# --- Filling in the portal -------------------------------------------------------------------------

def test_what_the_supplier_enters_is_checked(client, world):
    _join(client, _invite(client, world))
    for bad in ({"tax_id": "100234567800003", "pan": "AAACZ1234F"},     # a TRN from an Indian company
                {"tax_id": _gstin(), "pan": "12345"}, {"tax_id": _gstin()},
                {"tax_id": _gstin(), "pan": "AAACZ1234F", "answers": {"related_party": "maybe"}},
                {"tax_id": _gstin(), "pan": "AAACZ1234F", "answers": {"is_approved": "yes"}}):
        assert client.put("/portal/profile", json={"answers": ANSWERS, **bad}).status_code == 422, bad
    for bad in ({"account_number": "12", "ifsc": "HDFC0001234"}, {"account_number": _account(), "ifsc": "HDFC1001234"},
                {"account_number": _account()}):
        assert client.put("/portal/bank", json={"account_name": "Zenith", **bad}).status_code == 422, bad
    assert _upload(client, "passport").status_code == 422
    assert _upload(client, "pan", data=b"MZ\x90\x00 not a pdf").status_code == 422          # an .exe called .pdf
    assert _upload(client, "pan", data=b"<html><script>alert(1)</script>", content_type="text/html").status_code == 422
    assert client.post("/portal/submit").status_code == 422                                  # nothing filled in yet


def test_a_uae_supplier_uses_a_trn_and_an_iban(client, world):
    _join(client, _invite(client, world, country="AE", name="Gulf Supplies LLC"))
    assert client.put("/portal/profile", json={"tax_id": "100234567800003", "pan": "AAACZ1234F", "answers": ANSWERS}).status_code == 422
    assert client.put("/portal/profile", json={"tax_id": "100234567800003", "answers": ANSWERS}).status_code == 200
    bban = "0331234567890123456"
    check = 98 - int(bban + "101400") % 97
    good_iban = f"AE{check:02d}{bban}"
    bad_iban = f"AE{(check + 1) % 100:02d}{bban}"
    assert client.put("/portal/bank", json={"account_name": "Gulf", "account_number": bad_iban}).status_code == 422
    saved = client.put("/portal/bank", json={"account_name": "Gulf", "account_number": good_iban})
    assert saved.status_code == 200 and saved.json()["bank_last4"] == good_iban[-4:]


# --- Review ----------------------------------------------------------------------------------------

def test_a_clean_supplier_is_approved_handed_over_and_linked_by_the_sync(client, db, world):
    invited = _invite(client, world)
    _complete(client, invited)

    login(client, world.finance)
    detail = client.get(f"/suppliers/{invited['id']}").json()
    assert detail["risk"]["level"] == "low" and detail["allowed"]["decide"] is True
    assert "bank_details_encrypted" not in detail and len(detail["bank_last4"]) == 4
    assert client.post(f"/suppliers/{invited['id']}/handover").status_code == 409        # not approved yet
    assert _decide(client, world.buyer, invited["id"]).status_code == 403                # a buyer does not review
    approved = _decide(client, world.finance, invited["id"])
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert _decide(client, world.admin, invited["id"]).status_code == 409                # already decided
    assert client.post(f"/suppliers/{invited['id']}/handover").json()["status"] == "handed_over"

    # Orrfin created no vendor. A person adds it in the ERP; the next sync finds it by tax number.
    assert service.link_synced_vendors(db, world.org.id) == 0
    world.vendor.gstin = detail["tax_id"]
    db.commit()
    assert service.link_synced_vendors(db, world.org.id) == 1
    db.commit()
    linked = client.get(f"/suppliers/{invited['id']}").json()
    assert (linked["status"], linked["vendor_id"]) == ("active", str(world.vendor.id))
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == uuid.UUID(invited["id"]))
                         .order_by(AuditEvent.seq)).all()
    assert actions == ["invited", "invite_accepted", "profile_updated", "bank_details_set", "document_added",
                       "document_added", "document_added", "submitted", "approved", "handed_over",
                       "linked_to_erp_vendor"]


def test_the_person_who_invited_a_supplier_cannot_approve_it(client, world, factory):
    invited = _invite(client, world, by=world.finance)
    _complete(client, invited)
    assert _decide(client, world.finance, invited["id"]).status_code == 403
    assert client.get(f"/suppliers/{invited['id']}").json()["allowed"]["decide"] is False
    assert _decide(client, world.admin, invited["id"]).status_code == 200


def test_a_block_stops_approval_and_the_supplier_is_not_tipped_off(client, db, world):
    # The test database is emptied before each run, which also removes the list the migration seeds.
    db.add(SanctionsEntry(name="Shadow Freight Private Limited", country="IN", list_name="Orrfin synthetic list"))
    db.commit()
    sanctioned = _invite(client, world, name="Shadow Freight Pvt. Ltd.")
    _complete(client, sanctioned)
    assert "sanctions" not in " ".join(client.get("/portal/me").json()["to_do"]).lower()
    refused = _decide(client, world.finance, sanctioned["id"], reason="Looks fine to me")
    assert refused.status_code == 409 and "sanctions list" in refused.json()["detail"]
    detail = client.get(f"/suppliers/{sanctioned['id']}").json()
    assert detail["risk"]["level"] == "critical" and detail["on_hold"] is True
    assert _decide(client, world.finance, sanctioned["id"], "reject", "On the sanctions list").json()["status"] == "rejected"

    no_documents = _invite(client, world)
    _complete(client, no_documents, documents=("bank_proof",))
    assert _decide(client, world.finance, no_documents["id"], reason="ok").status_code == 409


def test_a_hold_needs_a_written_reason(client, world):
    invited = _invite(client, world, category="software")
    _complete(client, invited, documents=("tax_certificate", "pan"), answers={**ANSWERS, "data_security_policy": "no"})
    assert _decide(client, world.finance, invited["id"]).status_code == 422
    assert _decide(client, world.finance, invited["id"], "reject").status_code == 422      # a rejection needs one too
    approved = _decide(client, world.finance, invited["id"], reason="Bank letter seen on a call; policy due in 30 days")
    assert approved.status_code == 200 and approved.json()["risk"]["level"] == "medium"


def test_two_suppliers_cannot_share_a_bank_account(client, world):
    account = _account()
    first, second = _invite(client, world, name="First Supplies"), _invite(client, world, name="Second Supplies")
    _complete(client, first, account=account)
    _complete(client, second, account=account)
    refused = _decide(client, world.finance, second["id"], reason="ok")
    assert refused.status_code == 409 and "bank account" in refused.json()["detail"]


def test_changed_bank_details_send_an_approved_supplier_back_to_review(client, world):
    invited = _invite(client, world)
    _complete(client, invited)
    assert _decide(client, world.finance, invited["id"]).status_code == 200
    assert _portal_login(client, invited["email"]).status_code == 200
    assert client.put("/portal/profile", json={"tax_id": _gstin(), "pan": "AAACZ1234F", "answers": ANSWERS}).status_code == 409
    changed = client.put("/portal/bank", json={"account_name": "Zenith", "account_number": _account(), "ifsc": "ICIC0004321"})
    assert changed.status_code == 200 and changed.json()["status"] == "submitted"
    login(client, world.finance)
    codes = [f["code"] for f in client.get(f"/suppliers/{invited['id']}").json()["risk"]["findings"]]
    assert "BANK_RECENTLY_CHANGED" in codes
    assert _decide(client, world.finance, invited["id"]).status_code == 422               # the hold needs a reason


def test_a_critical_hold_is_cleared_by_a_named_reviewer_with_a_reason(client, db, world):
    invited = _invite(client, world)
    _complete(client, invited)
    supplier = db.get(Supplier, uuid.UUID(invited["id"]))
    supplier.on_hold, supplier.vendor_id = True, world.vendor.id
    db.commit()
    assert "supplier-risk hold" in service.hold_reason_for_vendor(db, world.org.id, world.vendor.id)
    login(client, world.buyer)
    assert client.post(f"/suppliers/{invited['id']}/clear-hold", json={"reason": "fine"}).status_code == 403
    login(client, world.finance)
    assert client.post(f"/suppliers/{invited['id']}/clear-hold", json={"reason": " "}).status_code == 422
    assert client.post(f"/suppliers/{invited['id']}/clear-hold", json={"reason": "Reviewed with compliance"}).status_code == 200
    db.expire_all()
    assert service.hold_reason_for_vendor(db, world.org.id, world.vendor.id) is None


def test_another_org_cannot_see_or_decide_a_supplier(client, factory, world):
    invited = _invite(client, world)
    _complete(client, invited)
    login(client, world.finance)
    document_id = client.get(f"/suppliers/{invited['id']}").json()["documents"][0]["id"]
    download = client.get(f"/suppliers/{invited['id']}/documents/{document_id}")
    assert download.content == PDF and download.headers["content-disposition"].startswith("attachment")

    other = factory.user(factory.org("Other org"), "admin")
    login(client, other)
    assert client.get("/suppliers").json() == []
    assert client.get(f"/suppliers/{invited['id']}").status_code == 404
    assert client.get(f"/suppliers/{invited['id']}/documents/{document_id}").status_code == 404
    assert client.post(f"/suppliers/{invited['id']}/decision", json={"decision": "approve"}).status_code == 404
    assert client.post(f"/suppliers/{invited['id']}/handover").status_code == 404
    assert date.today() and client.post(f"/suppliers/{invited['id']}/clear-hold", json={"reason": "x"}).status_code == 404
