"""End to end: each of the 12 evaluation invoices gives the result in its answer key (PROMPTS Step 8 "Done when").

One org, the Step 4 ERP data synced, and the invoices uploaded, read, confirmed and matched
in number order, through the API, exactly as a finance user would. The expected outcome,
failed rules and amount at risk come from evals/extraction/*.json (listed in docs/DEMO_DATA.md).
"""

import json
from decimal import Decimal

from app import job_handlers  # noqa: F401  (registers extract and match)
from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT
from app.jobs import drain
from app.modules.audit.service import verify_chain
from app.modules.sync.service import pull_from_erp
from tests.conftest import login

EVAL = REPO_ROOT / "evals" / "extraction"


def test_every_evaluation_invoice_gets_its_expected_result(client, db, factory):
    org = factory.org("Eval org")
    pull_from_erp(db, org.id, FakeErpnextAdapter(REPO_ROOT / "seed" / "erpnext"))
    db.commit()
    finance = factory.user(org, "finance", limit="5000000")
    login(client, finance)

    results = {}
    for key_path in sorted(EVAL.glob("*.json")):
        key = json.loads(key_path.read_text(encoding="utf-8"))
        uploaded = client.post("/invoices", files={"file": (key["file"], (EVAL / key["file"]).read_bytes(),
                                                            "application/pdf")})
        assert uploaded.status_code == 201, (key["file"], uploaded.text)
        invoice_id = uploaded.json()["id"]
        drain(db)
        # Confirm "as printed": the bad-GSTIN invoice must reach the rules to be stopped there.
        confirmed = client.post(f"/invoices/{invoice_id}/confirm", json={"acknowledge_issues": True})
        assert confirmed.status_code == 200, (key["file"], confirmed.text)
        drain(db)
        invoice = client.get(f"/invoices/{invoice_id}").json()
        # Distinct codes: e.g. invoice 06 over-bills two PO lines, which is one kind of exception.
        failed = sorted({r["code"] for r in invoice["match"]["rule_results"] if r["status"] == "fail"})
        results[key["file"]] = (invoice["status"], failed, Decimal(invoice["match"]["amount_at_risk"]))
        assert verify_chain(db, invoice_id), key["file"]

        expected = key["expected_match"]
        assert invoice["status"] == expected["outcome"], (key["file"], failed, invoice["match"]["explanation"])
        assert failed == sorted(expected["exceptions"]), key["file"]
        assert Decimal(invoice["match"]["amount_at_risk"]) == Decimal(expected["amount_at_risk"]), key["file"]
        assert invoice["match"]["explanation"], key["file"]

    # "The same file twice": uploading invoice 01 again is refused before anything else happens.
    again = client.post("/invoices", files={"file": ("again.pdf", (EVAL / "01-clean-match.pdf").read_bytes(),
                                                     "application/pdf")})
    assert again.status_code == 409
    assert len(results) == 12
