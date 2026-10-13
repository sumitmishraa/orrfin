"""§8 exactly-once write-back of draft bills, for every write-capable ERP (PROMPTS Step 14).

The named failure test: the ERP saves the draft, then the reply is lost (timeout) → the outbox row goes
UNKNOWN → the retry looks the bill up first → exactly one draft exists and the row ends CONFIRMED.
Also: a validation error ends FAILED and is shown; a worker killed after SENT never double-posts;
"Retry sync" on a confirmed bill says "already in <ERP> as X, no duplicate created".
"""

import pytest
from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import AuditEvent, ErpOutbox
from app.modules.erp_outbox import service as outbox
from app.modules.sync.service import pull_from_erp
from app.ports.erp import ErpUnknown
from tests.conftest import login
from tests.failure.erp_write_cases import CASES, Rejects, SavedThenTimedOut, drain_with_retries

EVAL = REPO_ROOT / "evals" / "extraction"


@pytest.fixture(params=sorted(CASES), ids=sorted(CASES))
def case(request):
    return CASES[request.param]


@pytest.fixture
def people(factory):
    org = factory.org()
    return org, factory.user(org, "finance", limit="5000000", name="Uploader"), \
        factory.user(org, "finance", limit="5000000", name="Reviewer")


def _approved_invoice(client, db, monkeypatch, people, adapter) -> str:
    """Mirror the adapter's ERP, then upload → confirm → match → approve invoice 01 with that adapter in place."""
    org, uploader, reviewer = people
    pull_from_erp(db, org.id, adapter)
    db.commit()
    monkeypatch.setattr(outbox, "get_adapter", lambda connection: adapter)
    login(client, uploader)
    invoice_id = client.post("/invoices", files={"file": ("i.pdf", (EVAL / "01-clean-match.pdf").read_bytes(),
                                                          "application/pdf")}).json()["id"]
    drain(db)
    assert client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True}).status_code == 200
    drain(db)
    login(client, reviewer)
    response = client.post(f"/invoices/{invoice_id}/decision", json={"decision": "approve"})
    assert response.status_code == 200, response.text
    return invoice_id


def _row(db, invoice_id) -> ErpOutbox:
    db.expire_all()
    return db.scalar(select(ErpOutbox).where(ErpOutbox.invoice_id == invoice_id))


def test_adapter_level_lookup_finds_a_bill_whose_reply_was_lost(case):
    adapter = case.build(lambda inner: SavedThenTimedOut(inner, case.is_bill_write))
    from tests.contract.test_erp_adapter_contract import _draft_bill

    bill = _draft_bill(adapter, "LOST-REPLY-1")
    with pytest.raises(ErpUnknown):
        adapter.create_draft_bill(bill)
    if case.multi_call_write:
        # Only the header was saved: the lookup removes the unfinished draft, so a retry writes it whole.
        assert adapter.find_bill(bill.vendor_ref, bill.supplier_invoice_no) is None
        assert case.count(adapter)["bills"] == 0
    else:
        assert adapter.find_bill(bill.vendor_ref, bill.supplier_invoice_no)
        assert case.count(adapter)["bills"] == 1


def test_saved_then_timed_out_ends_confirmed_with_exactly_one_bill(client, db, monkeypatch, people, case):
    adapter = case.build(lambda inner: SavedThenTimedOut(inner, case.is_bill_write))
    invoice_id = _approved_invoice(client, db, monkeypatch, people, adapter)
    assert _row(db, invoice_id).state == "PENDING"  # queued in the approval transaction

    drain_with_retries(db)

    row = _row(db, invoice_id)
    assert row.state == "CONFIRMED" and row.erp_doc_name
    assert case.count(adapter)["bills"] == 1  # exactly one draft in the ERP, whatever happened on the wire
    actions = [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == row.id)
                                            .order_by(AuditEvent.seq))]
    confirmed = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == row.id,
                                                   AuditEvent.action == "erp_draft_confirmed"))
    if case.multi_call_write:
        assert row.attempts == 2  # lookup removed the half draft, then the retry wrote it whole
        assert actions == ["erp_draft_queued", "erp_draft_sent", "erp_draft_unknown", "erp_draft_sent",
                           "erp_draft_confirmed"]
    else:
        assert row.attempts == 1  # the retry found the bill by lookup; it never posted again
        assert actions == ["erp_draft_queued", "erp_draft_sent", "erp_draft_unknown", "erp_draft_confirmed"]
        assert confirmed.payload["via"] == "lookup"

    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["erp_sync"]["state"] == "CONFIRMED" and detail["erp_sync"]["erp"]
    retry = client.post(f"/erp-outbox/{row.id}/retry").json()
    assert retry["message"].startswith(f"Already in {detail['erp_sync']['erp']} as {row.erp_doc_name}")
    assert case.count(adapter)["bills"] == 1


def test_validation_error_ends_failed_and_is_shown(client, db, monkeypatch, people, case):
    adapter = case.build(lambda inner: Rejects(inner, case.is_bill_write))
    invoice_id = _approved_invoice(client, db, monkeypatch, people, adapter)
    drain_with_retries(db)

    row = _row(db, invoice_id)
    assert row.state == "FAILED" and "rejected" in row.last_error
    assert case.count(adapter)["bills"] == 0
    sync = client.get(f"/invoices/{invoice_id}").json()["erp_sync"]
    assert sync["state"] == "FAILED" and sync["last_error"]


def test_a_worker_killed_after_sent_never_double_posts(client, db, monkeypatch, people, case):
    adapter = case.build(lambda inner: inner)
    invoice_id = _approved_invoice(client, db, monkeypatch, people, adapter)
    row = _row(db, invoice_id)
    # The crash: the bill reached the ERP, but the worker died before recording it.
    adapter.create_draft_bill(outbox.build_draft_bill(db, row))
    row.state, row.attempts = "SENT", 1
    db.commit()

    drain_with_retries(db)

    assert _row(db, invoice_id).state == "CONFIRMED"
    assert case.count(adapter)["bills"] == 1


def test_no_write_back_when_the_connection_cannot_hold_drafts(client, db, monkeypatch, people):
    adapter = CASES["erpnext"].build(lambda inner: inner)
    original = adapter.capabilities

    def read_only():
        caps = original()
        return caps.model_copy(update={"can_write_bill": False, "write_note": "This sandbox is read-only."})

    adapter.capabilities = read_only
    invoice_id = _approved_invoice(client, db, monkeypatch, people, adapter)
    assert _row(db, invoice_id) is None
    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["status"] == "approved" and detail["erp_sync"] is None
    assert detail["erp_sync_note"] == "This sandbox is read-only."
