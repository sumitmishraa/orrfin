"""Invoice decisions, segregation of duties and the audit trail (BUILD_PLAN §9; §11 M5; PROMPTS Step 9).

M5 acceptance: uploader approval → 403; over-limit → 403; org A cannot read org B → 404;
audit event count equals state changes; the hash chain verifies (and breaks if tampered with).
"""

from dataclasses import dataclass

import pytest
from sqlalchemy import select, text

from app import job_handlers  # noqa: F401
from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import AuditEvent, ReviewDecision
from app.modules.sync.service import pull_from_erp
from tests.conftest import login

EVAL = REPO_ROOT / "evals" / "extraction"


@dataclass
class Team:
    org: object
    uploader: object
    reviewer: object
    small_limit: object


@pytest.fixture
def team(db, factory) -> Team:
    org = factory.org()
    pull_from_erp(db, org.id, FakeErpnextAdapter(REPO_ROOT / "seed" / "erpnext"))
    db.commit()
    return Team(org, factory.user(org, "finance", limit="5000000", name="Uploader"),
                factory.user(org, "finance", limit="5000000", name="Reviewer"),
                factory.user(org, "finance", limit="1000", name="Small limit"))


def _matched(client, db, user, pdf: str = "01-clean-match") -> str:
    """Upload, read, confirm and match an evaluation invoice as `user`; return its id."""
    login(client, user)
    invoice_id = client.post("/invoices", files={"file": ("i.pdf", (EVAL / f"{pdf}.pdf").read_bytes(),
                                                          "application/pdf")}).json()["id"]
    drain(db)
    assert client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True}).status_code == 200
    drain(db)
    return invoice_id


def _decide(client, user, invoice_id, decision="approve", reason=None):
    login(client, user)
    return client.post(f"/invoices/{invoice_id}/decision", json={"decision": decision, "reason": reason})


def test_the_uploader_cannot_approve_their_own_invoice(client, db, team):
    invoice_id = _matched(client, db, team.uploader)

    response = _decide(client, team.uploader, invoice_id)

    assert response.status_code == 403 and "uploaded" in response.json()["detail"]


def test_someone_who_edited_the_fields_cannot_approve(client, db, team):
    login(client, team.uploader)
    invoice_id = client.post("/invoices", files={"file": ("i.pdf", (EVAL / "01-clean-match.pdf").read_bytes(),
                                                          "application/pdf")}).json()["id"]
    drain(db)
    login(client, team.reviewer)
    client.patch(f"/invoices/{invoice_id}", json={"fields": {"vendor_name": "Shreeji Office Supplies"}})
    client.post(f"/invoices/{invoice_id}/confirm", json={})
    drain(db)

    response = _decide(client, team.reviewer, invoice_id)

    assert response.status_code == 403 and "edited" in response.json()["detail"]


def test_approval_above_the_reviewers_limit_is_refused(client, db, team):
    invoice_id = _matched(client, db, team.uploader)

    response = _decide(client, team.small_limit, invoice_id)

    assert response.status_code == 403 and "limit" in response.json()["detail"]


def test_an_independent_reviewer_approves_a_matched_invoice(client, db, team):
    invoice_id = _matched(client, db, team.uploader)

    response = _decide(client, team.reviewer, invoice_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["decisions"][0]["reviewer_name"] == "Reviewer"
    assert body["allowed"]["decide"] is False  # decided once; no second decision


def test_approving_an_exception_needs_a_reason(client, db, team):
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "exception"

    assert _decide(client, team.reviewer, invoice_id).status_code == 422
    approved = _decide(client, team.reviewer, invoice_id, reason="Vendor's revised price list, agreed by email")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


def test_reject_and_request_correction_need_a_reason(client, db, team):
    invoice_id = _matched(client, db, team.uploader, "09-vendor-mismatch")

    assert _decide(client, team.reviewer, invoice_id, "reject").status_code == 422
    rejected = _decide(client, team.reviewer, invoice_id, "reject", "Wrong vendor for this PO")
    assert rejected.json()["status"] == "rejected"


def test_a_correction_request_reopens_the_fields_and_re_matches(client, db, team):
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    corrected = _decide(client, team.reviewer, invoice_id, "request_correction", "Ask the vendor for a credit note")
    assert corrected.json()["status"] == "correction_requested"

    login(client, team.uploader)
    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["allowed"]["edit"] is True
    assert client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True}).status_code == 200
    drain(db)
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "exception"


def test_a_stale_match_must_be_rerun_before_any_decision(client, db, team, owner_engine):
    invoice_id = _matched(client, db, team.uploader)
    with owner_engine.begin() as conn:  # the PO changes in the ERP after matching
        conn.execute(text("UPDATE purchase_orders SET erp_modified = now() WHERE org_id = :org "
                          "AND erp_ref = 'PUR-ORD-2026-00001'"), {"org": team.org.id})

    login(client, team.reviewer)
    assert client.get(f"/invoices/{invoice_id}").json()["outcome"] == "stale"
    assert _decide(client, team.reviewer, invoice_id).status_code == 409
    assert client.post(f"/invoices/{invoice_id}/rematch").status_code == 200
    drain(db)
    assert _decide(client, team.reviewer, invoice_id).status_code == 200


def test_only_finance_or_admin_decide(client, db, team, factory):
    invoice_id = _matched(client, db, team.uploader)

    for role in ("buyer", "approver"):
        assert _decide(client, factory.user(team.org, role, limit="9999999"), invoice_id).status_code == 403


def test_another_org_cannot_read_or_decide(client, db, team, factory):
    invoice_id = _matched(client, db, team.uploader)
    outsider = factory.user(factory.org("Other"), "finance", limit="9999999")

    login(client, outsider)
    assert client.get(f"/invoices/{invoice_id}").status_code == 404
    assert _decide(client, outsider, invoice_id).status_code == 404
    assert client.get(f"/audit/{invoice_id}").status_code == 404


def test_audit_events_equal_state_changes_and_the_chain_verifies(client, db, team, owner_engine):
    invoice_id = _matched(client, db, team.uploader)
    _decide(client, team.reviewer, invoice_id)

    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == invoice_id)
                         .order_by(AuditEvent.seq)).all()
    assert actions == ["uploaded", "extracted", "confirmed", "matched", "decision_approve"]
    assert db.scalar(select(ReviewDecision.decision).where(ReviewDecision.invoice_id == invoice_id)) == "approve"
    audit = client.get(f"/audit/{invoice_id}").json()
    assert audit["chain_valid"] is True and len(audit["events"]) == 5

    with owner_engine.begin() as conn:  # someone with database access rewrites history
        conn.execute(text("UPDATE audit_events SET action = 'tampered' WHERE entity_id = :id AND seq = 2"),
                     {"id": invoice_id})
    assert client.get(f"/audit/{invoice_id}").json()["chain_valid"] is False


def test_the_exception_inbox_is_ranked_by_amount_at_risk(client, db, team):
    small = _matched(client, db, team.uploader, "02-price-variance-7pct")  # ₹910 at risk
    large = _matched(client, db, team.uploader, "03-over-receipt-qty")  # ₹33,800 at risk

    login(client, team.reviewer)
    inbox = client.get("/invoices", params={"scope": "exceptions"}).json()

    assert [i["id"] for i in inbox] == [large, small]
    assert [i["amount_at_risk"] for i in inbox] == ["33800.00", "910.00"]


def test_the_control_graph_shows_the_whole_chain_for_an_invoice(client, db, team, factory):
    invoice_id = _matched(client, db, team.uploader)
    _decide(client, team.reviewer, invoice_id)

    graph = client.get("/control-graph", params={"invoice_id": invoice_id}).json()

    assert [n["kind"] for n in graph["nodes"]] == ["request", "po", "receipt", "invoice", "match", "decision",
                                                   "erp_draft"]
    states = {n["kind"]: n["state"] for n in graph["nodes"]}
    assert states == {"request": "skipped", "po": "done", "receipt": "done", "invoice": "done", "match": "done",
                      "decision": "done", "erp_draft": "pending"}
    login(client, factory.user(factory.org("Other"), "finance", limit="1"))
    assert client.get("/control-graph", params={"invoice_id": invoice_id}).status_code == 404


def test_requests_appear_in_the_audit_list(client, db, team):
    _matched(client, db, team.uploader)
    login(client, team.reviewer)

    entities = client.get("/audit/entities").json()

    assert any(e["entity_type"] == "invoice" for e in entities)
