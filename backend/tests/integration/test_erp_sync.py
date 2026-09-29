"""ERP pull sync (BUILD_PLAN §4 pull = upsert by erp_ref, skip if erp_modified unchanged; §11 M1)."""

import json
import shutil

from sqlalchemy import func, select

from app import job_handlers  # noqa: F401  (registers the erp_pull handler)
from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import AuditEvent, GoodsReceipt, GrnLine, PoLine, PurchaseOrder, Vendor
from app.modules.sync.service import pull_from_erp
from tests.conftest import login

FIXTURES = REPO_ROOT / "seed" / "erpnext"
MIRROR_TABLES = (Vendor, PurchaseOrder, PoLine, GoodsReceipt, GrnLine)


def _counts(db, org_id) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m).where(m.org_id == org_id))
            for m in MIRROR_TABLES}


def test_running_the_pull_twice_leaves_row_counts_unchanged(db, factory):
    org = factory.org()
    adapter = FakeErpnextAdapter(FIXTURES)

    first = pull_from_erp(db, org.id, adapter)
    db.commit()
    after_first = _counts(db, org.id)
    second = pull_from_erp(db, org.id, adapter)
    db.commit()

    assert after_first == {"vendors": 5, "purchase_orders": 8, "po_lines": 13,
                           "goods_receipts": 8, "grn_lines": 12}
    assert _counts(db, org.id) == after_first
    assert first["purchase_orders"]["created"] == 8
    assert second["purchase_orders"] == {"created": 0, "updated": 0, "unchanged": 8}


def test_a_changed_erp_document_is_updated_on_the_next_pull(db, factory, tmp_path):
    org = factory.org()
    for f in FIXTURES.iterdir():
        shutil.copy(f, tmp_path / f.name)
    pull_from_erp(db, org.id, FakeErpnextAdapter(tmp_path))
    db.commit()

    orders = json.loads((tmp_path / "purchase_orders.json").read_text())
    orders["data"][2]["status"] = "Closed"
    orders["data"][2]["modified"] = "2026-09-29 09:00:00.000000"
    (tmp_path / "purchase_orders.json").write_text(json.dumps(orders))
    result = pull_from_erp(db, org.id, FakeErpnextAdapter(tmp_path))
    db.commit()

    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == org.id,
                                               PurchaseOrder.erp_ref == "PUR-ORD-2026-00003"))
    assert result["purchase_orders"] == {"created": 0, "updated": 1, "unchanged": 7}
    assert po.status == "closed"


def test_receipt_lines_are_linked_to_their_po_lines(db, factory):
    org = factory.org()
    pull_from_erp(db, org.id, FakeErpnextAdapter(FIXTURES))
    db.commit()

    unlinked = db.scalar(select(func.count()).select_from(GrnLine)
                         .where(GrnLine.org_id == org.id, GrnLine.po_line_id.is_(None)))
    assert unlinked == 0


def test_sync_button_queues_a_job_that_the_worker_completes(client, db, factory):
    org = factory.org()
    login(client, factory.user(org, "finance", limit="1"))

    queued = client.post("/sync/erp")
    assert queued.status_code == 202
    assert drain(db) >= 1
    job = client.get(f"/jobs/{queued.json()['id']}").json()
    pos = client.get("/purchase-orders").json()

    assert job["status"] == "done", job
    assert job["result"]["purchase_orders"]["created"] == 8
    assert len(pos) == 8
    assert db.scalar(select(func.count()).select_from(AuditEvent)
                     .where(AuditEvent.org_id == org.id, AuditEvent.action == "erp_pull_completed")) == 1


def test_po_detail_shows_ordered_and_received_quantities(client, db, factory):
    org = factory.org()
    pull_from_erp(db, org.id, FakeErpnextAdapter(FIXTURES))
    db.commit()
    login(client, factory.user(org, "buyer"))
    po_id = next(p["id"] for p in client.get("/purchase-orders").json() if p["erp_ref"] == "PUR-ORD-2026-00002")

    detail = client.get(f"/purchase-orders/{po_id}").json()

    laptops = next(line for line in detail["lines"] if line["item_code"] == "IT-LAP-14-I5")
    assert (laptops["qty"], laptops["qty_received"]) == ("5.000", "3.000")
    assert detail["vendor_name"] == "Kaveri IT Solutions LLP"
    assert [r["erp_ref"] for r in detail["receipts"]] == ["MAT-PRE-2026-00002"]


def test_requesters_cannot_trigger_a_sync_and_other_orgs_see_nothing(client, db, factory):
    org_a, org_b = factory.org("A"), factory.org("B")
    pull_from_erp(db, org_a.id, FakeErpnextAdapter(FIXTURES))
    db.commit()
    po_a = db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == org_a.id))

    login(client, factory.user(org_b, "requester"))
    assert client.post("/sync/erp").status_code == 403
    assert client.get("/purchase-orders").json() == []
    assert client.get(f"/purchase-orders/{po_a.id}").status_code == 404
