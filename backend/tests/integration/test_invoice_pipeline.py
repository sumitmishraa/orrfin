"""Upload → extract job → review → confirm (BUILD_PLAN §7, §9 upload limits; §11 M3; PROMPTS Step 7).

Extraction uses the answer-key FakeExtractor (AI_PROVIDER=fake in conftest), so these tests
check the pipeline, not a model. Outages are simulated with an extractor that always fails.
The job queue is shared across tests, so assertions never depend on how many jobs ran.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app import job_handlers  # noqa: F401  (registers the extract handler)
from app.config import REPO_ROOT
from app.jobs import _claim_next, drain
from app.models import AuditEvent, FieldEdit, Invoice, Job
from app.modules.audit.service import verify_chain
from app.modules.invoices.providers import use_extractor
from app.ports.extractor import ExtractorUnavailable
from tests.conftest import login

EVAL = REPO_ROOT / "evals" / "extraction"


def _pdf(name: str = "01-clean-match") -> bytes:
    return (EVAL / f"{name}.pdf").read_bytes()


def _upload(client, data: bytes, name: str = "invoice.pdf", content_type: str = "application/pdf"):
    return client.post("/invoices", files={"file": (name, data, content_type)})


def _finance(factory):
    org = factory.org()
    return org, factory.user(org, "finance", limit="5000000")


def test_upload_is_read_into_fields_with_evidence(client, db, factory):
    _, finance = _finance(factory)
    login(client, finance)

    uploaded = _upload(client, _pdf())
    assert uploaded.status_code == 201 and uploaded.json()["status"] == "extracting"
    assert drain(db) >= 1
    invoice = client.get(f"/invoices/{uploaded.json()['id']}").json()

    assert invoice["status"] == "needs_review"
    assert (invoice["invoice_no"], invoice["total"], invoice["po_reference"]) == (
        "SOS/2026-27/0201", "54870.00", "PUR-ORD-2026-00001")
    assert [l["qty"] for l in invoice["lines"]] == ["100.000", "40.000"]
    assert invoice["issues"] == []
    assert invoice["extraction"]["simulated"] is True  # labelled: not an AI reading
    assert invoice["evidence"]["invoice_no"]["quote"] == "SOS/2026-27/0201"
    assert invoice["allowed"] == {"edit": True, "confirm": True, "decide": False, "approve_blocked_reason": None}


def test_the_same_file_twice_is_blocked(client, factory):
    _, finance = _finance(factory)
    login(client, finance)

    assert _upload(client, _pdf()).status_code == 201
    again = _upload(client, _pdf(), name="renamed.pdf")

    assert again.status_code == 409 and "Duplicate blocked" in again.json()["detail"]


def test_only_real_pdfs_are_accepted(client, factory):
    _, finance = _finance(factory)
    login(client, finance)

    assert _upload(client, b"not a pdf", content_type="application/pdf").status_code == 422
    assert _upload(client, _pdf(), name="x.png", content_type="image/png").status_code == 422


def test_only_finance_or_admin_can_upload_and_requesters_cannot_see_invoices(client, factory):
    org, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]

    login(client, factory.user(org, "buyer"))
    assert _upload(client, _pdf("02-price-variance-7pct")).status_code == 403
    assert client.get(f"/invoices/{invoice_id}").status_code == 200  # buyers may look
    login(client, factory.user(org, "requester"))
    assert client.get("/invoices").status_code == 403


def test_another_org_cannot_read_the_invoice_or_its_pdf(client, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]

    login(client, factory.user(factory.org("Other"), "finance", limit="1"))
    assert client.get(f"/invoices/{invoice_id}").status_code == 404
    assert client.get(f"/invoices/{invoice_id}/file").status_code == 404


def test_the_pdf_is_served_to_its_own_org(client, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]

    response = client.get(f"/invoices/{invoice_id}/file")

    assert response.status_code == 200 and response.content == _pdf()
    assert response.headers["content-type"] == "application/pdf"


class _AlwaysDown:
    def extract(self, pdf: bytes):
        raise ExtractorUnavailable("ThrottlingException: simulated Bedrock outage")


def test_an_ai_outage_retries_three_times_then_switches_to_manual_entry(client, db, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]

    with use_extractor(_AlwaysDown()):
        for _ in range(3):
            drain(db)
            # Skip the backoff wait instead of sleeping in a test.
            db.execute(text("UPDATE jobs SET run_after = now() WHERE status = 'queued'"))
            db.commit()
    invoice = client.get(f"/invoices/{invoice_id}").json()
    job = db.scalar(select(Job).where(Job.kind == "extract", Job.payload["invoice_id"].astext == invoice_id))

    assert (job.status, job.attempts) == ("failed", 3)
    assert invoice["status"] == "manual_entry"
    assert "simulated Bedrock outage" in invoice["extraction_error"]
    assert invoice["allowed"]["edit"] is True  # finance types the fields in by hand


def test_a_job_resumes_after_the_worker_is_killed(client, db, factory, owner_engine):
    _, finance = _finance(factory)
    login(client, finance)
    drain(db)  # empty the shared queue, so the job claimed below is this test's own
    invoice_id = _upload(client, _pdf()).json()["id"]

    claimed = _claim_next(db)  # the worker takes the job ... and dies before finishing it
    assert claimed is not None and claimed.payload["invoice_id"] == invoice_id
    with owner_engine.begin() as conn:  # ten minutes pass
        conn.execute(text("UPDATE jobs SET updated_at = :t WHERE id = :id"),
                     {"t": datetime.now(UTC) - timedelta(minutes=11), "id": claimed.id})
    db.expire_all()

    assert drain(db) >= 1  # a restarted worker picks the stale job up again
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "needs_review"


def test_edits_are_recorded_field_by_field_and_audited(client, db, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]
    drain(db)

    edited = client.patch(f"/invoices/{invoice_id}", json={"fields": {"total": "55000.00", "vendor_name": "Shreeji"}})

    assert edited.status_code == 200
    assert {i["code"] for i in edited.json()["issues"]} == {"TOTAL_MISMATCH"}
    edits = db.scalars(select(FieldEdit).where(FieldEdit.invoice_id == invoice_id)).all()
    assert {(e.field, e.old, e.new) for e in edits} == {
        ("total", "54870.00", "55000.00"), ("vendor_name", "Shreeji Office Supplies Pvt Ltd", "Shreeji")}
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == invoice_id)
                         .order_by(AuditEvent.seq)).all()
    assert actions == ["uploaded", "extracted", "fields_edited"]
    assert verify_chain(db, invoice_id)


def test_bad_input_in_a_money_field_is_refused(client, db, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf()).json()["id"]
    drain(db)

    assert client.patch(f"/invoices/{invoice_id}", json={"fields": {"total": "54,870"}}).status_code == 422


def test_confirm_is_blocked_by_failed_checks_unless_confirmed_as_printed(client, db, factory):
    _, finance = _finance(factory)
    login(client, finance)
    invoice_id = _upload(client, _pdf("07-bad-gstin")).json()["id"]
    drain(db)

    blocked = client.post(f"/invoices/{invoice_id}/confirm", json={})
    as_printed = client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True})

    assert blocked.status_code == 409
    assert as_printed.status_code == 200
    assert as_printed.json()["confirmed_by_name"] == finance.full_name
    assert db.get(Invoice, as_printed.json()["id"]).status != "needs_review"
