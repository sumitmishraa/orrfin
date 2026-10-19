"""Bank reconciliation and month-end close (BUILD_PLAN v2.4 change 32; ADR 0008; PROMPTS Step 26).

Done when: the mock bank's statement reconciles 100% by UTR end to end; a weaker match is only a
suggestion a person accepts; the same file twice is refused; closing needs a reason for every open item;
a closed month refuses invoice approvals dated in it until an admin reopens it; every step is audited.
"""

from datetime import date

from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.jobs import drain
from app.models import AuditEvent
from tests.conftest import login
from tests.integration.test_invoice_review import _decide as decide_invoice
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_payments import _run_with_invoice, _verified, pay  # noqa: F401  (fixture)


def _paid_run(client, db, pay):  # noqa: F811
    _verified(client, pay)
    run = _run_with_invoice(client, pay)
    client.post(f"/payment-runs/{run['id']}/submit")
    login(client, pay.admin)
    client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "confirmed by phone"})
    client.post(f"/payment-runs/{run['id']}/send")
    drain(db)
    return client.get(f"/payment-runs/{run['id']}").json()


def _upload(client, name, data: bytes):
    return client.post("/bank-statements", files={"file": (name, data, "text/csv")})


def test_the_mock_bank_statement_reconciles_fully_by_utr(client, db, pay):  # noqa: F811
    run = _paid_run(client, db, pay)
    statement = client.get(f"/payment-runs/{run['id']}/bank-statement").content
    uploaded = _upload(client, "mock.csv", statement)
    assert uploaded.status_code == 201, uploaded.text
    view = uploaded.json()
    assert view["counts"] == {"matched": 1, "suggested": 0, "unmatched": 0}
    assert view["lines"][0]["method"] == "utr" and view["unreconciled_payments"] == []
    assert _upload(client, "again.csv", statement).status_code == 409  # same file twice
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "statement_imported")) is not None


def test_a_match_without_a_utr_is_only_a_suggestion_a_person_accepts(client, db, pay):  # noqa: F811
    run = _paid_run(client, db, pay)
    today = date.today().isoformat()
    csv = (f"Date,Narration,Reference,Debit,Credit,Balance\n"
           f"{today},NEFT/SHREEJI OFFICE SUPPLIES/PAYMENT,BANKREF-1,{run['total_net']},,\n"
           f"{today},BANK CHARGES,CHG-1,118.00,,\n").encode()
    view = _upload(client, "manual.csv", csv).json()
    assert view["counts"] == {"matched": 0, "suggested": 1, "unmatched": 1}
    suggested = next(line for line in view["lines"] if line["status"] == "suggested")
    accepted = client.post(f"/bank-lines/{suggested['id']}/accept").json()
    assert accepted["counts"]["matched"] == 1
    undone = client.post(f"/bank-lines/{suggested['id']}/unmatch").json()
    assert undone["counts"]["matched"] == 0
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "bank_statement")))
    assert {"statement_imported", "match_accepted", "match_removed"} <= actions


def test_bad_statements_are_refused_and_other_roles_see_nothing(client, pay, factory):  # noqa: F811
    login(client, pay.payer)
    assert _upload(client, "bad.csv", b"When,What\n1,2\n").status_code == 422
    assert _upload(client, "bad2.csv", b"Date,Narration,Debit\nnot-a-date,x,1\n").status_code == 422
    login(client, factory.user(pay.team.org, "buyer"))
    assert client.get("/bank-statements").status_code == 403


def test_closing_a_month_locks_approvals_until_an_admin_reopens_it(client, db, team, factory):  # noqa: F811
    held = _matched(client, db, team.uploader, "02-price-variance-7pct")  # dated September 2026
    admin = factory.user(team.org, "admin", limit="10000000", name="Admin")
    login(client, team.reviewer)
    view = client.get("/close/2026-09").json()
    assert next(c for c in view["checklist"] if c["key"] == "invoices_decided")["open"] == 1
    assert view["received_not_invoiced"]  # September receipts not yet billed, at PO rates

    refused = client.post("/close/2026-09/close", json={"notes": {}})
    assert refused.status_code == 422 and "Explain each open item" in refused.json()["detail"]
    closed = client.post("/close/2026-09/close", json={"notes": {"invoices_decided": "Vendor revising the price", "gstr2b_imported": "2B due on the 14th"}})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert client.post("/close/2026-09/close", json={"notes": {}}).status_code == 409

    locked = decide_invoice(client, team.reviewer, held, reason="agreed")
    assert locked.status_code == 409 and "2026-09 is closed" in locked.json()["detail"]
    assert client.post("/close/2026-09/reopen", json={"reason": "late price fix"}).status_code == 403  # finance
    login(client, admin)
    assert client.post("/close/2026-09/reopen", json={"reason": "late price fix"}).json()["status"] == "open"
    assert decide_invoice(client, team.reviewer, held, reason="agreed").status_code == 200

    csv = client.get("/close/2026-09/received-not-invoiced.csv")
    assert csv.status_code == 200 and csv.text.startswith("Vendor,PO,Item code")
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "close_period", AuditEvent.org_id == team.org.id).order_by(AuditEvent.created_at)).all()
    assert actions == ["month_closed", "month_reopened"]
    assert client.post("/close/2099-01/close", json={"notes": {}}).status_code == 422  # not started yet
