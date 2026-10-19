"""Simulated payments (BUILD_PLAN v2.4 change 31, §6b, §6c, §9; ADR 0008; PROMPTS Step 25).

Done when: TDS and net to the paisa; every payment SoD rule → 403; bank details need a second
person; blocking risks stop submission and holds need a reason; the bank file total equals the run
total; the mock bank settles once with UTRs and writes a statement; nothing for other roles or orgs.
"""

import csv
import io
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.jobs import drain, enqueue
from app.models import AuditEvent, PaymentLine, PaymentRun, Vendor
from tests.conftest import login
from tests.integration.test_invoice_review import _decide as decide_invoice
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)

PROFILE = {"pan": "AAKFS1234B", "tds_section": "194C", "payee_type": "company", "account_name": "Shreeji Office Supplies",
           "bank_account": "50200012345678", "ifsc": "HDFC0001234"}


@dataclass
class Pay:
    team: object
    payer: object
    admin: object
    invoice_id: str
    vendor_id: str


@pytest.fixture
def pay(client, db, team, factory):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "01-clean-match")
    assert decide_invoice(client, team.reviewer, invoice_id).status_code == 200
    payer = factory.user(team.org, "finance", limit="5000000", name="Payer")
    admin = factory.user(team.org, "admin", limit="10000000", name="Admin")
    vendor = db.scalar(select(Vendor).where(Vendor.org_id == team.org.id, Vendor.name.ilike("Shreeji%")))
    return Pay(team, payer, admin, invoice_id, str(vendor.id))


def _profile(client, user, vendor_id, **overrides):
    login(client, user)
    return client.put(f"/payment-profiles/{vendor_id}", json={**PROFILE, **overrides})


def _verified(client, pay, **overrides):
    assert _profile(client, pay.payer, pay.vendor_id, **overrides).status_code == 200
    login(client, pay.admin)
    assert client.post(f"/payment-profiles/{pay.vendor_id}/verify").status_code == 200


def _run_with_invoice(client, pay):
    login(client, pay.payer)
    run = client.post("/payment-runs").json()
    added = client.post(f"/payment-runs/{run['id']}/invoices", json={"invoice_id": pay.invoice_id})
    assert added.status_code == 200, added.text
    return added.json()


# --- Profiles: maker-checker -----------------------------------------------------------------------------

def test_bank_details_need_a_second_person_and_the_audit_keeps_only_the_last_four_digits(client, db, pay):
    assert _profile(client, pay.payer, pay.vendor_id).status_code == 200
    assert client.post(f"/payment-profiles/{pay.vendor_id}/verify").status_code == 403  # the changer
    login(client, pay.admin)
    verified = client.post(f"/payment-profiles/{pay.vendor_id}/verify")
    assert verified.status_code == 200
    row = next(r for r in verified.json() if r["vendor_id"] == pay.vendor_id)
    assert row["profile"]["status"] == "verified" and row["profile"]["bank_account_last4"] == "…5678"
    payloads = [e.payload for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "vendor_payment_profile"))]
    assert "50200012345678" not in str(payloads) and any(p.get("account_new") == "…5678" for p in payloads)
    # Changing the bank account again sends it back to "pending verification".
    _profile(client, pay.payer, pay.vendor_id, bank_account="50200099990000")
    login(client, pay.admin)
    assert next(r for r in client.get("/payment-profiles").json()
                if r["vendor_id"] == pay.vendor_id)["profile"]["status"] == "pending_verification"


def test_bad_bank_details_are_refused(client, pay):
    assert _profile(client, pay.payer, pay.vendor_id, ifsc="HDFC1234567").status_code == 422
    assert _profile(client, pay.payer, pay.vendor_id, bank_account="12AB").status_code == 422


# --- TDS, risk, SoD and the mock bank ------------------------------------------------------------------------

def test_the_full_run_tds_holds_sod_bank_file_and_settlement(client, db, pay):
    _verified(client, pay)
    run = _run_with_invoice(client, pay)
    line = run["lines"][0]
    # 194C company 2% on the value before GST: 2% of ₹46,500.00 = ₹930.00; net = ₹54,870.00 − ₹930.00.
    assert (line["gross"], line["tds_amount"], line["net"]) == ("54870.00", "930.00", "53940.00")
    assert run["total_net"] == "53940.00" and run["total_tds"] == "930.00"
    assert {"FIRST_PAYMENT", "BANK_CHANGED_RECENTLY"} <= set(run["holds"]) and run["blocks"] == []

    assert client.post(f"/payment-runs/{run['id']}/submit").status_code == 200
    # Segregation of duties: not the preparer, not the invoice's approver, not above the limit.
    assert client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "ok"}).status_code == 403
    login(client, pay.team.reviewer)
    refused = client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "ok"})
    assert refused.status_code == 403 and "approved one of these invoices" in refused.json()["detail"]
    login(client, pay.team.small_limit)
    assert client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "ok"}).status_code == 403
    login(client, pay.admin)
    assert client.post(f"/payment-runs/{run['id']}/approve", json={}).status_code == 422  # holds need a reason
    approved = client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "Called vendor, details confirmed."})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    bank = client.get(f"/payment-runs/{run['id']}/bank-file")
    rows = list(csv.DictReader(io.StringIO(bank.text)))
    assert sum(Decimal(r["Amount"]) for r in rows) == Decimal("53940.00")
    assert rows[0]["Payment Type"] == "NEFT" and rows[0]["IFSC"] == "HDFC0001234"

    assert client.post(f"/payment-runs/{run['id']}/send").json()["status"] == "sent"
    drain(db)
    settled = client.get(f"/payment-runs/{run['id']}").json()
    assert settled["status"] == "settled" and settled["lines"][0]["utr"].startswith("SIMN")
    statement = client.get(f"/payment-runs/{run['id']}/bank-statement").text
    assert settled["lines"][0]["utr"] in statement and "53940.00" in statement

    # The mock bank settles once: a second job for the same run changes nothing.
    db.expire_all()
    enqueue(db, org_id=pay.team.org.id, kind="bank_settle", payload={"run_id": run["id"]})
    db.commit()
    drain(db)
    utrs = db.scalars(select(PaymentLine.utr).where(PaymentLine.run_id == run["id"])).all()
    assert len(utrs) == 1 and utrs[0] == settled["lines"][0]["utr"]

    # A paid invoice can never be paid again.
    login(client, pay.payer)
    again = client.post("/payment-runs").json()
    blocked = client.post(f"/payment-runs/{again['id']}/invoices", json={"invoice_id": pay.invoice_id}).json()
    assert "ALREADY_PAID" in blocked["blocks"]
    assert client.post(f"/payment-runs/{again['id']}/submit").status_code == 409


def test_unverified_bank_details_block_submission(client, pay):
    assert _profile(client, pay.payer, pay.vendor_id).status_code == 200  # not verified
    run = _run_with_invoice(client, pay)
    assert "BANK_UNVERIFIED" in run["blocks"]
    refused = client.post(f"/payment-runs/{run['id']}/submit")
    assert refused.status_code == 409 and "not yet verified" in refused.json()["detail"]


def test_the_mock_bank_can_reject_a_payment(client, db, pay):
    _verified(client, pay, ifsc="ORFN0000000")
    run = _run_with_invoice(client, pay)
    client.post(f"/payment-runs/{run['id']}/submit")
    login(client, pay.admin)
    client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "demo"})
    client.post(f"/payment-runs/{run['id']}/send")
    drain(db)
    result = client.get(f"/payment-runs/{run['id']}").json()
    assert result["status"] == "partly_failed" and result["lines"][0]["status"] == "failed"
    assert "invalid" in result["lines"][0]["failure_reason"]
    # A failed payment does not count as paid: the invoice is eligible again.
    assert any(i["invoice_id"] == pay.invoice_id for i in client.get("/payments/eligible").json())


def test_other_roles_and_orgs_see_nothing(client, db, pay, factory):
    _verified(client, pay)
    run = _run_with_invoice(client, pay)
    buyer = factory.user(pay.team.org, "buyer")
    login(client, buyer)
    assert client.get("/payment-runs").status_code == 403
    assert client.get(f"/payment-runs/{run['id']}").status_code == 403
    stranger = factory.user(factory.org("Other Org"), "finance", limit="1")
    login(client, stranger)
    assert client.get(f"/payment-runs/{run['id']}").status_code == 404
    assert db.scalar(select(PaymentRun.status).where(PaymentRun.id == run["id"])) == "draft"


def test_the_dashboard_shows_payments(client, db, pay):
    _verified(client, pay)
    run = _run_with_invoice(client, pay)
    login(client, pay.payer)
    section = client.get("/insights/summary", params={"period": "all"}).json()["sections"]["payments"]
    assert section["in_runs"] == "53940.00" and section["due"] == "0.00"
    assert run["status"] == "draft"
