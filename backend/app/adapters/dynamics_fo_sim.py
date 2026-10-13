"""A simulated Dynamics 365 F&O OData endpoint (/data/<Entity>), in-process via httpx.MockTransport
(PROMPTS Step 17).

Serves the canonical dataset as F&O data entities and accepts Orrfin's draft writes: GET /data/<Entity> with
$filter, POST /data/<Entity>, DELETE /data/<Entity>(dataAreaId='orf',<Key>='...'). Like F&O it refuses an
unknown vendor account or item (400 with an `error.innererror.message`).
"""

import re
from typing import Any

import httpx

from app.adapters.sim_rest import Collections, json_error, json_reply, load, odata_filter
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

KEYS = {"VendorsV2": "VendorAccountNumber", "PurchaseOrderHeadersV2": "PurchaseOrderNumber",
        "PurchaseOrderLinesV2": "_id", "ProductReceiptLines": "_id", "VendorInvoiceHeaders": "HeaderReference",
        "VendorInvoiceLines": "_id", "ReleasedProductsV2": "ItemNumber"}
DELETE_KEY = re.compile(r"^/(\w+)\(dataAreaId='orf',(\w+)='((?:[^']|'')*)'\)$")


def render() -> dict[str, list[dict[str, Any]]]:
    data = dataset()
    docs: dict[str, list[dict[str, Any]]] = {name: [] for name in KEYS}
    for v in data.vendors:
        docs["VendorsV2"].append({"_id": f"V-{v.key}", "dataAreaId": "orf", "VendorAccountNumber": f"V-{v.key}",
                                  "VendorOrganizationName": v.name, "TaxExemptNumber": v.gstin})
    for code in sorted({line.item_code for po in data.purchase_orders for line in po.lines}):
        docs["ReleasedProductsV2"].append({"_id": code, "ItemNumber": code})
    for n, po in enumerate(data.purchase_orders, start=1):
        number = f"PO-{n:06d}"
        docs["PurchaseOrderHeadersV2"].append({
            "_id": number, "dataAreaId": "orf", "PurchaseOrderNumber": number,
            "OrderVendorAccountNumber": f"V-{po.vendor.key}", "AccountingDate": po.po_date.isoformat(),
            "RequestedDeliveryDate": po.schedule_date.isoformat(), "DocumentApprovalStatus": "Confirmed",
            "PurchaseOrderStatus": "Received" if po.status == "to_bill" else "Backorder", "CurrencyCode": "INR",
            "VendorOrderReference": po.number})
        for i, line in enumerate(po.lines, start=1):
            docs["PurchaseOrderLinesV2"].append({
                "_id": f"{number}/{i}", "PurchaseOrderNumber": number, "LineNumber": i, "ItemNumber": line.item_code,
                "LineDescription": line.item_name, "HSNCode": line.hsn, "PurchaseUnitSymbol": line.uom,
                "OrderedPurchaseQuantity": line.qty, "PurchasePrice": line.rate, "LineAmount": line.amount,
                "SalesTaxItemGroupCode": f"GST{line.tax_rate.normalize()}"})
        for receipt in po.receipts:
            for k, (index, qty) in enumerate(receipt.quantities.items(), start=1):
                docs["ProductReceiptLines"].append({
                    "_id": f"{receipt.number}/{k}", "ProductReceiptNumber": receipt.number, "LineNumber": k,
                    "ProductReceiptDate": receipt.posting_date.isoformat(), "PurchaseOrderNumber": number,
                    "PurchaseOrderLineNumber": index + 1, "ItemNumber": po.lines[index].item_code,
                    "ReceivedInventoryQuantity": qty})
    return docs


def _write_failed(message: str) -> httpx.Response:
    return json_reply(400, {"error": {"message": "Write failed", "innererror": {"message": message}}})


class FakeDynamicsFo:
    def __init__(self, store: SimStore):
        self.data = Collections(store, render, id_field="_id")

    def _live(self, entity: str) -> list[dict[str, Any]]:
        return [d for d in self.data.all(entity) if not d.get("_deleted")]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/data", 1)[-1]
        if request.method == "DELETE":
            m = DELETE_KEY.match(path)
            if not m:
                return json_error(400, "BadRequest", "Unsupported key")
            entity, field, value = m.groups()
            value = value.replace("''", "'")
            for doc in self._live(entity):
                if doc.get(field) == value:
                    self.data.put(entity, {**doc, "_deleted": True})
                    return httpx.Response(204)
            return json_error(404, "NotFound", "No such record")
        entity = path.strip("/")
        if entity not in KEYS:
            return json_error(404, "NotFound", f"Entity {entity} not found")
        if request.method == "GET":
            try:
                keep = odata_filter(request.url.params.get("$filter"))
            except ValueError as exc:
                return json_error(400, "BadRequest", str(exc))
            return json_reply(200, {"value": [d for d in self._live(entity) if keep(d)]})
        if request.method != "POST":
            return json_error(405, "MethodNotAllowed", request.method)
        body = load(request)
        vendors = {v["VendorAccountNumber"] for v in self._live("VendorsV2")}
        items = {i["ItemNumber"] for i in self._live("ReleasedProductsV2")}
        account = body.get("InvoiceAccount") or body.get("OrderVendorAccountNumber")
        if entity in ("VendorInvoiceHeaders", "PurchaseOrderHeadersV2") and account not in vendors:
            return _write_failed(f"Vendor account {account} does not exist.")
        if entity in ("VendorInvoiceLines", "PurchaseOrderLinesV2") and body.get("ItemNumber") not in items:
            return _write_failed(f"Item number {body.get('ItemNumber')} does not exist.")
        key = KEYS[entity]
        if key == "_id":
            doc_id = f"{body.get('HeaderReference') or body.get('PurchaseOrderNumber')}/{body.get('LineNumber')}"
        else:
            doc_id = body.get(key)
            if any(d.get(key) == doc_id for d in self._live(entity)):
                return _write_failed(f"{entity} {doc_id} already exists.")
        return json_reply(201, self.data.put(entity, {**body, "_id": doc_id}))
