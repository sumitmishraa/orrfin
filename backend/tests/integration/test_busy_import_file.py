"""BUSY, the file-based connector, end to end through the real registry (BUILD_PLAN §8; PROMPTS Step 16).

With BUSY (simulated) active: sync → upload, confirm, match invoice 01 → approve → the outbox writes ONE
XML import file, offers it for download, and "Retry sync" finds it instead of writing a second file.
"""

from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import ErpOutbox
from tests.conftest import login
from tests.failure.erp_write_cases import drain_with_retries

EVAL = REPO_ROOT / "evals" / "extraction"


def test_approving_with_busy_active_writes_one_downloadable_import_file(client, db, factory):
    org = factory.org()
    admin = factory.user(org, "admin", limit="10000000")
    uploader = factory.user(org, "finance", limit="5000000", name="Uploader")
    reviewer = factory.user(org, "finance", limit="5000000", name="Reviewer")

    login(client, admin)
    busy = next(c for c in client.get("/connectors").json() if c["system"] == "busy")
    assert client.post(f"/connectors/connections/{busy['simulated']['id']}/activate").status_code == 200
    client.post("/sync/erp")
    drain(db)
    assert len(client.get("/purchase-orders").json()) == 8

    login(client, uploader)
    invoice_id = client.post("/invoices", files={"file": ("i.pdf", (EVAL / "01-clean-match.pdf").read_bytes(),
                                                          "application/pdf")}).json()["id"]
    drain(db)
    client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True})
    drain(db)
    login(client, reviewer)
    assert client.post(f"/invoices/{invoice_id}/decision", json={"decision": "approve"}).status_code == 200
    drain_with_retries(db)

    sync = client.get(f"/invoices/{invoice_id}").json()["erp_sync"]
    assert sync["state"] == "CONFIRMED" and sync["erp"] == "BUSY" and sync["import_file_url"]
    download = client.get(sync["import_file_url"])
    assert download.status_code == 200 and download.headers["content-type"].startswith("application/xml")
    assert b"<SupplierInvoiceNo>" in download.content and b"orrfin:" in download.content

    retry = client.post(f"/erp-outbox/{sync['id']}/retry").json()
    assert retry["message"].startswith(f"Already in BUSY as {sync['erp_doc_name']}")
    db.expire_all()
    assert db.scalar(select(ErpOutbox).where(ErpOutbox.invoice_id == invoice_id)).attempts == 1


def test_requesters_cannot_download_import_files(client, db, factory):
    org = factory.org()
    requester = factory.user(org, "requester")
    login(client, requester)
    response = client.get("/erp-outbox/00000000-0000-0000-0000-000000000000/import-file")
    assert response.status_code == 403
