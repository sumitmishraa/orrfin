"""A simulated Oracle Fusion REST endpoint (/fscmRestApi/resources/11.13.18.05), in-process via
httpx.MockTransport (PROMPTS Step 19).

Serves suppliers, purchaseOrders (lines only with expand=lines), receivingReceiptTransactions, invoices and
draftPurchaseOrders, with Fusion's paging (limit, offset, hasMore) and query-by-example `q=Field='v';Field2='v'`.
Like Fusion it refuses an unknown supplier or a duplicate invoice number per supplier (400 with "detail").
"""

import re
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.oracle_fusion import API
from app.adapters.sim_rest import Collections, json_reply, load
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

RESOURCES = ("suppliers", "purchaseOrders", "receivingReceiptTransactions", "invoices", "draftPurchaseOrders")
_QBE = re.compile(r"^(\w+)='((?:[^']|'')*)'$")
STATUS = {"closed": "CLOSED", "to_bill": "CLOSED FOR RECEIVING", "open": "OPEN"}


def _bad(message: str) -> httpx.Response:
    return json_reply(400, {"title": "Bad Request", "detail": message, "o:errorCode": "27024"})


def render() -> dict[str, list[dict[str, Any]]]:
    data = dataset()
    docs: dict[str, list[dict[str, Any]]] = {name: [] for name in RESOURCES}
    number_of = {}
    for n, v in enumerate(data.vendors, start=1):
        number_of[v.key] = f"{1250 + n}"
        docs["suppliers"].append({"_id": str(n), "SupplierId": 300000 + n, "SupplierNumber": number_of[v.key],
                                  "Supplier": v.name, "TaxpayerId": v.gstin, "LastUpdateDate": v.modified.isoformat()})
    for n, po in enumerate(data.purchase_orders, start=1):
        number = f"US{164000 + n}"
        docs["purchaseOrders"].append({
            "_id": number, "POHeaderId": 400000 + n, "OrderNumber": number, "SupplierNumber": number_of[po.vendor.key],
            "Supplier": po.vendor.name, "OrderDate": po.po_date.isoformat(),
            "RequestedDeliveryDate": po.schedule_date.isoformat(), "Status": STATUS[po.status],
            "CurrencyCode": "INR", "Ordered": po.net_total, "TotalTax": po.tax_total, "Total": po.grand_total,
            "SupplierOrder": po.number, "Description": "", "LastUpdateDate": po.modified.isoformat(),
            "lines": [{"LineNumber": i, "Item": line.item_code, "Description": line.item_name, "UOM": line.uom,
                       "Quantity": line.qty, "Price": line.rate, "Amount": line.amount, "TaxRate": line.tax_rate}
                      for i, line in enumerate(po.lines, start=1)]})
        for receipt in po.receipts:
            for k, (index, qty) in enumerate(receipt.quantities.items(), start=1):
                docs["receivingReceiptTransactions"].append({
                    "_id": f"{receipt.number}/{k}", "ReceiptNumber": receipt.number, "ReceiptLineNumber": k,
                    "TransactionType": "RECEIVE", "TransactionDate": receipt.modified.isoformat(),
                    "DocumentNumber": number, "DocumentLineNumber": index + 1,
                    "ItemNumber": po.lines[index].item_code, "Quantity": qty})
    return docs


class FakeOracleFusion:
    def __init__(self, store: SimStore):
        self.data = Collections(store, render, id_field="_id")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith(API + "/"):
            return json_reply(404, {"title": "Not Found", "detail": "Unknown resource"})
        resource = request.url.path[len(API) + 1:].strip("/")
        if resource not in RESOURCES:
            return json_reply(404, {"title": "Not Found", "detail": f"Unknown resource {resource}"})
        if request.method == "GET":
            return self._list(resource, request.url.params)
        if request.method != "POST":
            return json_reply(405, {"title": "Method Not Allowed"})
        return self._create(resource, load(request))

    def _list(self, resource: str, params) -> httpx.Response:
        rows = self.data.all(resource)
        for clause in filter(None, (params.get("q") or "").split(";")):
            m = _QBE.match(clause.strip())
            if not m:
                return _bad(f"Invalid query: {clause}")
            field, value = m.group(1), m.group(2).replace("''", "'")
            rows = [r for r in rows if str(r.get(field) or "") == value]
        if params.get("expand") != "lines":
            rows = [{k: v for k, v in r.items() if k not in ("lines", "invoiceLines")} for r in rows]
        limit, offset = int(params.get("limit", 25)), int(params.get("offset", 0))
        page = rows[offset:offset + limit]
        return json_reply(200, {"items": page, "count": len(page), "hasMore": offset + limit < len(rows),
                                "limit": limit, "offset": offset, "links": []})

    def _create(self, resource: str, body: dict[str, Any]) -> httpx.Response:
        suppliers = {s["SupplierNumber"] for s in self.data.all("suppliers")}
        if body.get("SupplierNumber") not in suppliers:
            return _bad(f"The supplier {body.get('SupplierNumber')} isn't valid.")
        if resource == "invoices":
            for other in self.data.all("invoices"):
                if other["SupplierNumber"] == body["SupplierNumber"] and other["InvoiceNumber"] == body.get("InvoiceNumber"):
                    return _bad(f"The invoice number {body['InvoiceNumber']} already exists for this supplier.")
            invoice_id = self.data.next_number("invoices", 600000)
            doc = {**body, "_id": str(invoice_id), "InvoiceId": invoice_id, "ValidationStatus": "Not validated"}
        elif resource == "draftPurchaseOrders":
            number = f"US{self.data.next_number('draftPurchaseOrders', 170000)}"
            # Like Fusion, line amounts and the order total are computed on save.
            lines = [{**ln, "Amount": str(Decimal(str(ln["Quantity"])) * Decimal(str(ln["Price"])))}
                     for ln in body.get("lines") or []]
            ordered = sum((Decimal(ln["Amount"]) for ln in lines), Decimal("0"))
            doc = {**body, "_id": number, "OrderNumber": number, "Status": "INCOMPLETE", "lines": lines,
                   "Ordered": str(ordered), "TotalTax": "0", "Total": str(ordered)}
        else:
            return json_reply(405, {"title": "Method Not Allowed", "detail": f"Cannot create {resource}"})
        return json_reply(201, self.data.put(resource, doc))
