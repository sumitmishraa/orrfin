"""GSTR-2B matching end to end (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Matching only, no filing.

Done when: the seed GSTR-2B matches invoice 01, flags invoice 02's different value, shows invoice 03 as
missing (its ₹24,336.00 of credit at risk) and lists a supplier invoice Orrfin has not seen; the same
file twice is refused; the dashboard, the payment hold and the close checklist use the result.
"""

from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.config import REPO_ROOT
from app.models import AuditEvent
from tests.conftest import login
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)

FIXTURE = (REPO_ROOT / "seed" / "gstr2b" / "2026-09.json").read_bytes()


def _upload(client, data=FIXTURE, name="2026-09.json"):
    return client.post("/gstr2b", files={"file": (name, data, "application/json")})


def test_the_seed_gstr2b_matches_flags_and_puts_credit_at_risk(client, db, team):  # noqa: F811
    for pdf in ("01-clean-match", "02-price-variance-7pct", "03-over-receipt-qty"):
        _matched(client, db, team.uploader, pdf)
    login(client, team.reviewer)
    uploaded = _upload(client)
    assert uploaded.status_code == 201, uploaded.text
    view = uploaded.json()["current"]
    assert view["period"] == "2026-09"
    status = {ln["invoice_no"]: ln["status"] for ln in view["lines"]}
    assert status == {"SOS/2026-27/0201": "matched", "SPS/26-27/0412": "amount_differs", "DFS/2026/1190": "not_in_books"}
    assert [m["invoice_no"] for m in view["missing_in_2b"]] == ["KITS/INV/2026/0877"]
    assert view["itc_at_risk"] == "24336.00"
    assert _upload(client).status_code == 409  # the same file twice
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "gstr2b_imported")) is not None

    section = client.get("/insights/summary", params={"period": "all"}).json()["sections"]["gst"]
    assert section["itc_at_risk"] == "24336.00" and section["missing_in_2b"] == 1
    item = next(c for c in client.get("/close/2026-09").json()["checklist"] if c["key"] == "gstr2b_imported")
    assert item["ok"] is True


def test_bad_files_and_other_roles_are_refused(client, team, factory):  # noqa: F811
    login(client, team.reviewer)
    assert _upload(client, b"not json", "x.json").status_code == 422
    assert _upload(client, b'{"data": {"rtnprd": "132026"}}', "y.json").status_code == 422
    login(client, factory.user(team.org, "buyer"))
    assert client.get("/gstr2b").status_code == 403


# --- Photo / handwritten bills (Step 27) -----------------------------------------------------------------

PHOTOS = REPO_ROOT / "evals" / "extraction-photos"


def test_a_photo_of_a_handwritten_bill_goes_upload_extract_confirm_match(client, db, team):  # noqa: F811
    from app.jobs import drain

    login(client, team.uploader)
    data = (PHOTOS / "14-photo-handwritten.png").read_bytes()
    created = client.post("/invoices", files={"file": ("bill.png", data, "image/png")})
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]
    drain(db)
    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["invoice_no"] == "SOS/2026-27/0232" and detail["total"] == "54870.00"
    assert client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True}).status_code == 200
    drain(db)
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "matched"
    served = client.get(f"/invoices/{invoice_id}/file")
    assert served.headers["content-type"] == "image/png" and served.content == data


def test_a_file_that_is_not_what_it_claims_is_refused(client, team):  # noqa: F811
    login(client, team.uploader)
    pdf = (REPO_ROOT / "evals" / "extraction" / "01-clean-match.pdf").read_bytes()
    assert client.post("/invoices", files={"file": ("x.png", pdf, "image/png")}).status_code == 422
    assert client.post("/invoices", files={"file": ("x.gif", b"GIF89a....", "image/gif")}).status_code == 422
