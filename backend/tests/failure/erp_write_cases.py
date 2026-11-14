"""Write-capable ERP adapters for the §8 failure tests (PROMPTS Step 14: "make the failure test a reusable
fixture so Steps 16-20 run it for each adapter").

Each case builds a fresh adapter whose HTTP transport can be wrapped (to inject "saved, then timed out"
or a validation error), and says how to count the documents its server really holds. Later steps add
their connectors to CASES; the tests in this folder then cover them without changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update

from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_fake import SIMULATED_BASE_URL
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.adapters.tally import TallyAdapter
from app.adapters.tally_sim import DEMO_COMPANY, FakeTallyServer
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import Job
from app.ports.erp import ErpAdapter
from app.security.outbound import ErpHttp

Wrap = Callable[[httpx.BaseTransport], httpx.BaseTransport]


@dataclass
class WriteCase:
    name: str
    build: Callable[[Wrap], ErpAdapter]
    count: Callable[[ErpAdapter], dict[str, int]]  # {"bills": n, "pos": n} as the ERP itself holds them
    is_bill_write: Callable[[httpx.Request], bool]
    is_po_write: Callable[[httpx.Request], bool]
    # What a person does in the ERP to turn Orrfin's draft PO into a real one (Step 15 "submit it").
    submit_po: Callable[[ErpAdapter, str], None] | None = None
    # Header + lines in separate calls (Business Central): a reply lost after the header leaves an unfinished
    # draft, which the lookup removes; the retry then writes the whole draft (attempt 2), still exactly one.
    multi_call_write: bool = False


def _erpnext_build(wrap: Wrap) -> ErpAdapter:
    server = FakeFrappeServer(REPO_ROOT / "seed" / "erpnext", SimStore(None))
    adapter = ErpnextAdapter(ErpHttp(base_url=SIMULATED_BASE_URL, transport=wrap(httpx.MockTransport(server)),
                                     erp_name="ERPNext (simulated)"), label="simulated")
    adapter.server = server
    return adapter


def _erpnext_count(adapter) -> dict[str, int]:
    docs = adapter.server._docs(adapter.server.store.load())
    return {"bills": len(docs.get("Purchase Invoice", {})),
            "pos": sum(1 for d in docs.get("Purchase Order", {}).values() if d.get("orrfin_ref"))}


def _is_post(path: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path.replace("%20", " ") == path


def _tally_build(wrap: Wrap) -> ErpAdapter:
    server = FakeTallyServer(SimStore(None))
    adapter = TallyAdapter(ErpHttp(base_url="http://localhost:9000", transport=wrap(httpx.MockTransport(server)),
                                   erp_name="TallyPrime (simulated)"), company=DEMO_COMPANY, label="simulated",
                           educational=False)
    adapter.server = server
    return adapter


def _tally_vouchers(adapter) -> list[dict]:
    return list(adapter.server._objects(adapter.server.store.load())["VOUCHER"].values())


def _tally_count(adapter) -> dict[str, int]:
    optional = [v for v in _tally_vouchers(adapter) if v.get("ISOPTIONAL") == "Yes"]
    return {"bills": sum(v["VOUCHERTYPENAME"] == "Purchase" for v in optional),
            "pos": sum(v["VOUCHERTYPENAME"] == "Purchase Order" for v in _tally_vouchers(adapter)
                       if "orrfin:" in (v.get("NARRATION") or ""))}


def _tally_regularise(adapter, number: str) -> None:
    """What a person does in Tally: turn the optional voucher into a regular one."""
    state = adapter.server.store.load()
    vouchers = state["objects"]["VOUCHER"]
    for key, vch in vouchers.items():
        if vch.get("VOUCHERNUMBER") == number:
            vouchers[key] = {**vch, "ISOPTIONAL": "No", "ALTERID": str(int(vch["ALTERID"]) + 1)}
    adapter.server.store.save(state)


def _tally_import(vch_type: str) -> Callable[[httpx.Request], bool]:
    return lambda r: b"Import Data" in r.content and f'VCHTYPE="{vch_type}"'.encode() in r.content


def _bc_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.business_central import API_HOST, TOKEN_HOST, BusinessCentralAdapter
    from app.adapters.business_central_sim import FakeBusinessCentral

    server = FakeBusinessCentral(SimStore(None))
    transport = wrap(httpx.MockTransport(server))
    adapter = BusinessCentralAdapter(
        ErpHttp(base_url=f"{API_HOST}/v2.0/t1/Production/api/v2.0", transport=transport, erp_name="Business Central"),
        ErpHttp(base_url=TOKEN_HOST, transport=transport, erp_name="Microsoft Entra"),
        tenant="t1", client_id="c1", client_secret="s", company_name=None, label="simulated")
    adapter.server = server
    return adapter


def _bc_count(adapter) -> dict[str, int]:
    live = adapter.server._live
    return {"bills": len(live("purchaseInvoices")),
            "pos": sum(str(o.get("vendorOrderNumber") or "").startswith("ORF-") for o in live("purchaseOrders"))}


def _bc_release(adapter, number: str) -> None:
    """What a person does in Business Central: release the draft PO (API status Open)."""
    for order in adapter.server._live("purchaseOrders"):
        if order.get("number") == number:
            adapter.server.data.put("purchaseOrders", {**order, "status": "Open",
                                                       "lastModifiedDateTime": "2026-10-13T10:00:00Z"})


def _ends(path: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path.endswith(path)


def _fo_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.dynamics_fo import DynamicsFoAdapter
    from app.adapters.dynamics_fo_sim import FakeDynamicsFo

    server = FakeDynamicsFo(SimStore(None))
    adapter = DynamicsFoAdapter(ErpHttp(base_url="https://orrfin-demo.operations.dynamics.com/data",
                                        transport=wrap(httpx.MockTransport(server)), erp_name="F&O (simulated)"))
    adapter.server = server
    return adapter


def _fo_count(adapter) -> dict[str, int]:
    live = adapter.server._live
    return {"bills": len(live("VendorInvoiceHeaders")),
            "pos": sum(str(h.get("VendorOrderReference") or "").startswith("ORF-") for h in live("PurchaseOrderHeadersV2"))}


def _fo_confirm(adapter, number: str) -> None:
    """What a person does in F&O: approve and confirm the draft purchase order."""
    for header in adapter.server._live("PurchaseOrderHeadersV2"):
        if header["PurchaseOrderNumber"] == number:
            adapter.server.data.put("PurchaseOrderHeadersV2", {**header, "DocumentApprovalStatus": "Confirmed"})


def _sap_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.sap_s4 import SapS4Adapter
    from app.adapters.sap_s4_sim import FakeSapS4

    server = FakeSapS4(SimStore(None))
    http = ErpHttp(base_url="https://sap.test", transport=wrap(httpx.MockTransport(server)), erp_name="SAP (simulated)")
    adapter = SapS4Adapter(http, http, label="simulated")
    adapter.server = server
    return adapter


def _sap_count(adapter) -> dict[str, int]:
    return {"bills": len(adapter.server.data.all("A_SupplierInvoice")),
            "pos": len(adapter.server.data.all("A_PurchaseRequisitionHeader"))}


def _b1_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.sap_b1 import SapB1Adapter
    from app.adapters.sap_b1_sim import FakeSapB1

    server = FakeSapB1(SimStore(None))
    http = ErpHttp(base_url="https://b1.test/b1s/v1", transport=wrap(httpx.MockTransport(server)),
                   erp_name="SAP B1 (simulated)")
    adapter = SapB1Adapter(http, company_db="SBODEMOIN", user="manager", password="x")
    adapter.server = server
    return adapter


def _b1_count(adapter) -> dict[str, int]:
    drafts = adapter.server.data.all("Drafts")
    return {"bills": sum(d["DocObjectCode"] == "oPurchaseInvoices" for d in drafts),
            "pos": sum(d["DocObjectCode"] == "oPurchaseOrders" for d in drafts)}


def _b1_add_from_draft(adapter, name: str) -> None:
    """What a person does in B1: open the draft and Add it as a real purchase order."""
    from decimal import Decimal

    entry = int(name.split()[-1])
    draft = next(d for d in adapter.server.data.all("Drafts") if d["DocEntry"] == entry)
    lines = []
    for i, line in enumerate(draft["DocumentLines"]):
        qty, price = Decimal(str(line["Quantity"])), Decimal(str(line["UnitPrice"]))
        lines.append({**line, "LineNum": i, "Quantity": str(qty), "UnitPrice": str(price),
                      "LineTotal": str(qty * price), "TaxCode": "GST18"})
    net = sum((Decimal(line["LineTotal"]) for line in lines), Decimal("0"))
    vat = (net * Decimal("0.18")).quantize(Decimal("0.01"))
    doc_entry = 100 + entry
    adapter.server.data.put("PurchaseOrders", {
        "_id": str(doc_entry), "DocEntry": doc_entry, "DocNum": 1000 + doc_entry, "CardCode": draft["CardCode"],
        "DocDate": draft["DocDate"], "DocDueDate": draft["DocDueDate"], "DocumentStatus": "bost_Open",
        "DocTotal": str(net + vat), "VatSum": str(vat), "NumAtCard": None, "Comments": draft["Comments"],
        "UpdateDate": "2026-10-13", "UpdateTime": "10:00:00", "DocumentLines": lines})


def _sap_post(entity: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path.endswith(f"/{entity}")


def _b1_draft(kind: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path.endswith("/Drafts") and kind.encode() in r.content


def _oracle_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.oracle_fusion import OracleFusionAdapter
    from app.adapters.oracle_fusion_sim import FakeOracleFusion

    server = FakeOracleFusion(SimStore(None))
    adapter = OracleFusionAdapter(ErpHttp(base_url="https://oracle.test", erp_name="Oracle (simulated)",
                                          transport=wrap(httpx.MockTransport(server))))
    adapter.server = server
    return adapter


def _oracle_count(adapter) -> dict[str, int]:
    return {"bills": len(adapter.server.data.all("invoices")),
            "pos": len(adapter.server.data.all("draftPurchaseOrders"))}


def _oracle_submit(adapter, number: str) -> None:
    """What a person does in Fusion: submit the draft; it becomes an open purchase order."""
    from decimal import Decimal

    draft = next(d for d in adapter.server.data.all("draftPurchaseOrders") if d["OrderNumber"] == number)
    lines = [{**ln, "Amount": str(Decimal(str(ln["Quantity"])) * Decimal(str(ln["Price"]))), "TaxRate": "18"}
             for ln in draft["lines"]]
    adapter.server.data.put("purchaseOrders", {**draft, "_id": number, "Status": "OPEN", "lines": lines,
                                               "LastUpdateDate": "2026-10-13T10:00:00+05:30"})


def _netsuite_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.netsuite import NetSuiteAdapter
    from app.adapters.netsuite_sim import FakeNetSuite

    server = FakeNetSuite(SimStore(None))
    adapter = NetSuiteAdapter(ErpHttp(base_url="https://netsuite.test", erp_name="NetSuite (simulated)",
                                      transport=wrap(httpx.MockTransport(server))))
    adapter.server = server
    return adapter


def _netsuite_count(adapter) -> dict[str, int]:
    return {"bills": len(adapter.server.data.all("vendorBill")),
            "pos": sum(1 for p in adapter.server.data.all("purchaseOrder") if p.get("externalId"))}


def _netsuite_approve(adapter, tran_id: str) -> None:
    """What a person does in NetSuite: approve the pending purchase order."""
    from app.adapters.netsuite import APPROVED

    po = next(p for p in adapter.server.data.all("purchaseOrder") if p.get("tranId") == tran_id)
    adapter.server.data.put("purchaseOrder", {**po, "approvalStatus": {"id": APPROVED, "refName": "Approved"},
                                              "lastModifiedDate": "2026-10-13T10:00:00+00:00"})


def _put(path_part: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "PUT" and path_part in r.url.path


def _zoho_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.zoho_books import ACCOUNTS_HOST, API_BASE, ZohoBooksAdapter
    from app.adapters.zoho_books_sim import ORG_ID, REFRESH, FakeZohoBooks

    server = FakeZohoBooks(SimStore(None))
    transport = wrap(httpx.MockTransport(server))
    adapter = ZohoBooksAdapter(ErpHttp(base_url=API_BASE, transport=transport, erp_name="Zoho Books (simulated)"),
                               ErpHttp(base_url=ACCOUNTS_HOST, transport=transport, erp_name="Zoho Accounts"),
                               client_id="c", client_secret="s", refresh_token=REFRESH, organization_id=ORG_ID,
                               label="simulated", bill_drafts_checked=True)
    adapter.server = server
    return adapter


def _zoho_count(adapter) -> dict[str, int]:
    pos = adapter.server.data["purchaseorders"].all("purchaseorders")
    return {"bills": len(adapter.server.data["bills"].all("bills")),
            "pos": sum(str(p.get("reference_number") or "").startswith("ORF-") for p in pos)}


def _zoho_open(adapter, number: str) -> None:
    """What a person does in Zoho Books: mark the draft purchase order as open (issued)."""
    store = adapter.server.data["purchaseorders"]
    po = next(p for p in store.all("purchaseorders") if p["purchaseorder_number"] == number)
    store.put("purchaseorders", {**po, "status": "open", "last_modified_time": "2026-10-13T10:00:00+05:30"})


def _odoo_build(wrap: Wrap) -> ErpAdapter:
    from app.adapters.odoo import OdooAdapter
    from app.adapters.odoo_sim import FakeOdoo

    server = FakeOdoo(SimStore(None))
    adapter = OdooAdapter(ErpHttp(base_url="http://localhost:8069", transport=wrap(httpx.MockTransport(server)),
                                  erp_name="Odoo (simulated)"), label="simulated")
    adapter.server = server
    return adapter


def _odoo_count(adapter) -> dict[str, int]:
    models = adapter.server.store.load().get("models", {})
    return {"bills": sum(1 for m in models.get("account.move", {}).values() if m.get("move_type") == "in_invoice"),
            "pos": sum(1 for p in models.get("purchase.order", {}).values()
                       if str(p.get("origin") or "").startswith("orrfin:"))}


def _odoo_confirm(adapter, name: str) -> None:
    """What a person does in Odoo: confirm the RFQ, which makes it a purchase order."""
    po = adapter.call("purchase.order", "search_read", domain=[["name", "=", name]], fields=["id"])[0]
    adapter.call("purchase.order", "button_confirm", ids=[po["id"]])


def _json2(model: str, needle: bytes = b"") -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path == f"/json/2/{model}/create" and needle in r.content


CASES: dict[str, WriteCase] = {
    "zoho_books": WriteCase("zoho_books", _zoho_build, _zoho_count,
                            lambda r: r.method == "POST" and r.url.path.endswith("/books/v3/bills"),
                            lambda r: r.method == "POST" and r.url.path.endswith("/books/v3/purchaseorders"),
                            submit_po=_zoho_open),
    "odoo": WriteCase("odoo", _odoo_build, _odoo_count, _json2("account.move"), _json2("purchase.order", b"orrfin:"),
                      submit_po=_odoo_confirm),
    "oracle_fusion": WriteCase("oracle_fusion", _oracle_build, _oracle_count, _sap_post("invoices"),
                               _sap_post("draftPurchaseOrders"), submit_po=_oracle_submit),
    "netsuite": WriteCase("netsuite", _netsuite_build, _netsuite_count, _put("/vendorBill/eid:"),
                          _put("/purchaseOrder/eid:"), submit_po=_netsuite_approve),
    "sap_s4": WriteCase("sap_s4", _sap_build, _sap_count, _sap_post("A_SupplierInvoice"),
                        _sap_post("A_PurchaseRequisitionHeader")),
    "sap_b1": WriteCase("sap_b1", _b1_build, _b1_count, _b1_draft("oPurchaseInvoices"), _b1_draft("oPurchaseOrders"),
                        submit_po=_b1_add_from_draft),
    "dynamics_fo": WriteCase("dynamics_fo", _fo_build, _fo_count, _ends("/VendorInvoiceHeaders"),
                             _ends("/PurchaseOrderHeadersV2"), submit_po=_fo_confirm, multi_call_write=True),
    "business_central": WriteCase("business_central", _bc_build, _bc_count, _ends("/purchaseInvoices"),
                                  _ends("/purchaseOrders"), submit_po=_bc_release, multi_call_write=True),
    "tally": WriteCase("tally", _tally_build, _tally_count, _tally_import("Purchase"),
                       _tally_import("Purchase Order"), submit_po=_tally_regularise),
    "erpnext": WriteCase("erpnext", _erpnext_build, _erpnext_count,
                         _is_post("/api/resource/Purchase Invoice"), _is_post("/api/resource/Purchase Order"),
                         submit_po=lambda adapter, name: adapter._submit("Purchase Order", name)),
}


class SavedThenTimedOut(httpx.BaseTransport):
    """The ERP does the work, then the reply is lost — once (§8 "the POST succeeds, then times out")."""

    def __init__(self, inner: httpx.BaseTransport, when: Callable[[httpx.Request], bool]):
        self.inner, self.when, self.fired = inner, when, 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        if self.when(request) and not self.fired:
            self.fired += 1
            raise httpx.ReadTimeout("simulated: saved in the ERP, reply lost", request=request)
        return response


class Rejects(httpx.BaseTransport):
    """The ERP refuses the write with a validation error, like ERPNext's 417."""

    def __init__(self, inner: httpx.BaseTransport, when: Callable[[httpx.Request], bool]):
        self.inner, self.when = inner, when

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.when(request):
            return httpx.Response(417, json={"exc_type": "ValidationError",
                                             "_server_messages": '["{\\"message\\": \\"Item IT-X is disabled\\"}"]'})
        return self.inner.handle_request(request)


def drain_with_retries(db, rounds: int = 6) -> None:
    """Run jobs, including retries the queue scheduled for later (backoff), until nothing is waiting."""
    for _ in range(rounds):
        drain(db)
        moved = db.execute(update(Job).where(Job.status == "queued")
                           .values(run_after=datetime.now(UTC) - timedelta(seconds=1))).rowcount
        db.commit()
        if not moved:
            return



def _dialect_case(system: str) -> WriteCase:
    from app.adapters.dialect_rest import DialectAdapter, dig
    from app.adapters.dialect_rest_sim import FakeDialectServer
    from app.adapters.dialects import BY_SYSTEM

    d = BY_SYSTEM[system]

    def build(wrap: Wrap) -> ErpAdapter:
        server = FakeDialectServer(d, SimStore(None))
        adapter = DialectAdapter(ErpHttp(base_url=d.base_url, transport=wrap(httpx.MockTransport(server)),
                                         erp_name=f"{d.name} (simulated)"), d)
        adapter.server = server
        return adapter

    def count(adapter) -> dict[str, int]:
        drafts = [p for p in adapter.server.data.all("pos") if dig(p, d.f["po_status"]) == d.draft_value]
        return {"bills": len(adapter.server.data.all("bills")), "pos": len(drafts)}

    def posts_to(logical: str) -> Callable[[httpx.Request], bool]:
        return lambda r: r.method == "POST" and r.url.path.endswith("/" + d.collections[logical])

    return WriteCase(system, build, count, posts_to("bills"), posts_to("po_drafts"))


# Step 36: the dialect-based connectors run the same lost-reply and validation tests. QuickBooks Online, Xero
# and TallyPrime UAE are left out here on purpose: these tests need an invoice that passes three-way matching
# against the canonical (Indian GST) data, and those three cannot give one (no goods receipts in QuickBooks
# and Xero; VAT instead of GST in Tally UAE). Their draft writes and lookups are covered by the contract suite.
for _system in ("sage_intacct", "sage_50", "acumatica", "focus_x", "marg"):
    CASES[_system] = _dialect_case(_system)
