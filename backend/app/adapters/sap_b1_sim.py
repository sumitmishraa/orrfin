"""A simulated SAP Business One Service Layer (/b1s/v1), in-process via httpx.MockTransport (PROMPTS Step 18).

POST /Login sets a B1SESSION cookie; every other call without it gets 401, as the Service Layer does. Serves the
canonical dataset as BusinessPartners, Items, PurchaseOrders and PurchaseDeliveryNotes, and stores Drafts.
Like B1 it refuses a draft for an unknown CardCode or ItemCode (400 with error.message.value).
"""

from typing import Any

import httpx

from app.adapters.sim_rest import Collections, json_reply, load, odata_filter
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

SESSION = "sim-b1-session"
ENTITIES = ("BusinessPartners", "Items", "PurchaseOrders", "PurchaseDeliveryNotes", "Drafts")


def _b1_error(status: int, code: int, message: str) -> httpx.Response:
    return json_reply(status, {"error": {"code": code, "message": {"lang": "en-us", "value": message}}})


def render() -> dict[str, list[dict[str, Any]]]:
    data = dataset()
    docs: dict[str, list[dict[str, Any]]] = {name: [] for name in ENTITIES}
    for v in data.vendors:
        docs["BusinessPartners"].append({"_id": f"S{v.key[1:]}", "CardCode": f"S{v.key[1:]}", "CardName": v.name,
                                         "CardType": "cSupplier", "FederalTaxID": v.gstin,
                                         "UpdateDate": v.modified.date().isoformat(),
                                         "UpdateTime": v.modified.strftime("%H:%M:%S")})
    for code in sorted({line.item_code for po in data.purchase_orders for line in po.lines}):
        docs["Items"].append({"_id": code, "ItemCode": code})
    note_no = 0
    for n, po in enumerate(data.purchase_orders, start=1):
        docs["PurchaseOrders"].append({
            "_id": str(n), "DocEntry": n, "DocNum": 1000 + n, "CardCode": f"S{po.vendor.key[1:]}",
            "DocDate": po.po_date.isoformat(), "DocDueDate": po.schedule_date.isoformat(),
            "DocumentStatus": "bost_Close" if po.closed else "bost_Open", "DocCurrency": "INR",
            "DocTotal": po.grand_total, "VatSum": po.tax_total, "NumAtCard": po.number, "Comments": "",
            "UpdateDate": po.po_date.isoformat(), "UpdateTime": "16:30:00",
            "DocumentLines": [{"LineNum": i, "ItemCode": line.item_code, "ItemDescription": line.item_name,
                               "Quantity": line.qty, "UnitPrice": line.rate, "LineTotal": line.amount,
                               "TaxCode": f"GST{line.tax_rate.normalize()}", "MeasureUnit": line.uom}
                              for i, line in enumerate(po.lines)]})
        for receipt in po.receipts:
            note_no += 1
            docs["PurchaseDeliveryNotes"].append({
                "_id": str(note_no), "DocEntry": note_no, "DocNum": 2000 + note_no, "CardCode": f"S{po.vendor.key[1:]}",
                "DocDate": receipt.posting_date.isoformat(), "UpdateDate": receipt.posting_date.isoformat(),
                "UpdateTime": "18:05:00",
                "DocumentLines": [{"LineNum": k, "ItemCode": po.lines[index].item_code, "Quantity": qty,
                                   "BaseType": 22, "BaseEntry": n, "BaseLine": index}
                                  for k, (index, qty) in enumerate(receipt.quantities.items())]})
    return docs


class FakeSapB1:
    def __init__(self, store: SimStore):
        self.data = Collections(store, render, id_field="_id")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/b1s/v1", 1)[-1].strip("/")
        if path == "Login" and request.method == "POST":
            return json_reply(200, {"SessionId": SESSION, "Version": "1000190", "SessionTimeout": 30},
                              headers={"Set-Cookie": f"B1SESSION={SESSION}; Path=/b1s; HttpOnly"})
        if f"B1SESSION={SESSION}" not in request.headers.get("cookie", ""):
            return _b1_error(401, 301, "Invalid session or session already timeout.")
        if path not in ENTITIES:
            return _b1_error(404, -1, f"Unknown resource {path}")
        if request.method == "GET":
            try:
                keep = odata_filter(request.url.params.get("$filter"))
            except ValueError as exc:
                return _b1_error(400, -1, str(exc))
            return json_reply(200, {"value": [d for d in self.data.all(path) if keep(d)]})
        if request.method != "POST" or path != "Drafts":
            return _b1_error(405, -1, "Only Drafts can be created through Orrfin")
        body = load(request)
        if body.get("CardCode") not in {bp["CardCode"] for bp in self.data.all("BusinessPartners")}:
            return _b1_error(400, -10, f"Invalid BP code '{body.get('CardCode')}'")
        items = {i["ItemCode"] for i in self.data.all("Items")}
        for line in body.get("DocumentLines") or []:
            if line.get("ItemCode") not in items:
                return _b1_error(400, -10, f"Invalid item code '{line.get('ItemCode')}'")
        entry = self.data.next_number("drafts", 500)
        return json_reply(201, self.data.put("Drafts", {**body, "_id": str(entry), "DocEntry": entry}))
