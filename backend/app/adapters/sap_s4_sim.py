"""A simulated SAP S/4HANA Cloud OData V2 endpoint, in-process via httpx.MockTransport (PROMPTS Step 18).

Serves the canonical dataset as A_Supplier, A_PurchaseOrder (+ items) and A_MaterialDocumentHeader (+ items)
in OData V2 JSON ({"d": {"results": [...]}}, "/Date(ms)/", decimal strings), and accepts Orrfin's simulated
writes with SAP's CSRF handshake: a GET with `x-csrf-token: Fetch` returns a token, and a POST without it is
refused with 403, as SAP does. Deep inserts of A_SupplierInvoice and A_PurchaseRequisitionHeader are stored
whole. Used for the Simulated connector, for the write side of the Sandbox connector (`with_reads=False`:
the suppliers then live in SAP's sandbox, so references aren't checked here), and in tests.
"""

import re
from typing import Any

import httpx

from app.adapters.sap_s4 import ODATA, to_sap_date
from app.adapters.sim_rest import Collections, json_reply, load, odata_filter
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

CSRF_TOKEN = "sim-csrf-token"
PATH = re.compile(rf"^{ODATA}/(?P<service>\w+)/(?P<entity>\w*)$")


def _v2_error(status: int, message: str) -> httpx.Response:
    return json_reply(status, {"error": {"code": "SY/530", "message": {"lang": "en", "value": message}}})


def render(with_reads: bool = True) -> dict[str, list[dict[str, Any]]]:
    docs: dict[str, list[dict[str, Any]]] = {"A_Supplier": [], "A_PurchaseOrder": [], "A_MaterialDocumentHeader": [],
                                             "A_SupplierInvoice": [], "A_PurchaseRequisitionHeader": [],
                                             "A_Product": []}
    if not with_reads:
        return docs
    data = dataset()
    supplier = {v.key: f"1000{v.key[1:]}" for v in data.vendors}
    for v in data.vendors:
        docs["A_Supplier"].append({"_id": v.key, "Supplier": supplier[v.key], "SupplierName": v.name,
                                   "TaxNumber3": v.gstin})
    for code in sorted({line.item_code for po in data.purchase_orders for line in po.lines}):
        docs["A_Product"].append({"_id": code, "Product": code})
    for n, po in enumerate(data.purchase_orders, start=1):
        number = f"45000000{n:02d}"
        docs["A_PurchaseOrder"].append({
            "_id": number, "PurchaseOrder": number, "Supplier": supplier[po.vendor.key],
            "PurchaseOrderDate": to_sap_date(po.po_date), "DocumentCurrency": "INR",
            "CorrespncExternalReference": po.number,
            "to_PurchaseOrderItem": {"results": [{
                "PurchaseOrder": number, "PurchaseOrderItem": f"{i * 10:05d}", "Material": line.item_code,
                "PurchaseOrderItemText": line.item_name, "OrderQuantity": str(line.qty),
                "PurchaseOrderQuantityUnit": line.uom, "NetPriceAmount": str(line.rate), "NetPriceQuantity": "1",
                "TaxCode": f"G{line.tax_rate.normalize()}"} for i, line in enumerate(po.lines, start=1)]}})
        for r_no, receipt in enumerate(po.receipts, start=1):
            doc = f"50000{n:02d}{r_no:03d}"
            docs["A_MaterialDocumentHeader"].append({
                "_id": doc, "MaterialDocument": doc, "MaterialDocumentYear": str(receipt.posting_date.year),
                "PostingDate": to_sap_date(receipt.posting_date),
                "to_MaterialDocumentItem": {"results": [{
                    "MaterialDocument": doc, "MaterialDocumentItem": str(k), "GoodsMovementType": "101",
                    "PurchaseOrder": number, "PurchaseOrderItem": f"{(index + 1) * 10:05d}",
                    "Material": po.lines[index].item_code, "QuantityInEntryUnit": str(qty),
                    "Supplier": supplier[po.vendor.key]}
                    for k, (index, qty) in enumerate(receipt.quantities.items(), start=1)]}})
    return docs


class FakeSapS4:
    def __init__(self, store: SimStore, *, with_reads: bool = True, api_key: str | None = None):
        self.data = Collections(store, lambda: render(with_reads), id_field="_id")
        self.validate_references = with_reads
        self.api_key = api_key

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.api_key and request.headers.get("APIKey") != self.api_key:
            return json_reply(401, {"fault": {"faultstring": "Invalid ApiKey"}})
        m = PATH.match(request.url.path)
        if not m:
            return _v2_error(404, "Resource not found")
        entity = m["entity"]
        if request.method == "GET" and not entity:
            # Service document; also SAP's CSRF handshake.
            headers = {"x-csrf-token": CSRF_TOKEN} if request.headers.get("x-csrf-token") == "Fetch" else {}
            return json_reply(200, {"d": {"EntitySets": []}}, headers)
        if request.method == "GET":
            try:
                keep = odata_filter(request.url.params.get("$filter"))
            except ValueError as exc:
                return _v2_error(400, str(exc))
            return json_reply(200, {"d": {"results": [d for d in self.data.all(entity) if keep(d)]}})
        if request.method != "POST":
            return _v2_error(405, "Method not allowed")
        if request.headers.get("x-csrf-token") != CSRF_TOKEN:
            return _v2_error(403, "CSRF token validation failed")
        body = load(request)
        problem = self._problem(entity, body) if self.validate_references else None
        if problem:
            return _v2_error(400, problem)
        if entity == "A_SupplierInvoice":
            number = str(self.data.next_number("invoice", 5105600000))
            doc = {**body, "_id": number, "SupplierInvoice": number, "FiscalYear": "2026"}
        elif entity == "A_PurchaseRequisitionHeader":
            number = str(self.data.next_number("requisition", 10000000))
            doc = {**body, "_id": number, "PurchaseRequisition": number}
        else:
            return _v2_error(400, f"Cannot create {entity}")
        return json_reply(201, {"d": self.data.put(entity, doc)})

    def _problem(self, entity: str, body: dict[str, Any]) -> str | None:
        suppliers = {s["Supplier"] for s in self.data.all("A_Supplier")}
        products = {p["Product"] for p in self.data.all("A_Product")}
        if entity == "A_SupplierInvoice" and body.get("InvoicingParty") not in suppliers:
            return f"Supplier {body.get('InvoicingParty')} does not exist"
        if entity == "A_PurchaseRequisitionHeader":
            for item in (body.get("to_PurchaseReqnItem") or {}).get("results", []):
                if item.get("Material") not in products:
                    return f"Material {item.get('Material')} does not exist"
                if item.get("FixedSupplier") not in suppliers:
                    return f"Supplier {item.get('FixedSupplier')} does not exist"
        return None
