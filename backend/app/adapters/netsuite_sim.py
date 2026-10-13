"""A simulated NetSuite SuiteTalk REST endpoint (/services/rest/record/v1), in-process via httpx.MockTransport
(PROMPTS Step 19).

Lists return ids only; GET <record>/<id> or <record>/eid:<externalId> returns the record with sublists;
PUT <record>/eid:<externalId> upserts (create or update by external ID, never a second record), replying
204 like NetSuite. Filters: `field IS "v"` and `entity ANY_OF [id]`, joined by AND. Unknown vendors or items
are refused with 400 and NetSuite's "o:errorDetails".
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.netsuite import APPROVED, RECORD
from app.adapters.sim_rest import Collections, json_reply, load
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

RECORDS = ("vendor", "inventoryItem", "purchaseOrder", "itemReceipt", "vendorBill")
_IS = re.compile(r'^(\w+)\s+IS\s+"((?:[^"\\]|\\.)*)"$')
_ANY = re.compile(r"^(\w+)\s+ANY_OF\s+\[([^\]]*)\]$")
STATUS = {"closed": "Closed", "to_bill": "Pending Bill", "open": "Pending Receipt"}


def _ns_error(status: int, detail: str) -> httpx.Response:
    return json_reply(status, {"title": "Bad Request", "status": status,
                               "o:errorDetails": [{"detail": detail, "o:errorCode": "INVALID_KEY_OR_REF"}]})


def render() -> dict[str, list[dict[str, Any]]]:
    data = dataset()
    docs: dict[str, list[dict[str, Any]]] = {name: [] for name in RECORDS}
    vendor_id = {}
    for n, v in enumerate(data.vendors, start=1):
        vendor_id[v.key] = str(100 + n)
        docs["vendor"].append({"id": vendor_id[v.key], "entityId": v.name, "companyName": v.name, "taxIdNum": v.gstin,
                               "lastModifiedDate": v.modified.isoformat()})
    for n, code in enumerate(sorted({line.item_code for po in data.purchase_orders for line in po.lines}), start=1):
        docs["inventoryItem"].append({"id": str(500 + n), "itemId": code})
    receipt_no = 0
    for n, po in enumerate(data.purchase_orders, start=1):
        po_id = str(900 + n)
        docs["purchaseOrder"].append({
            "id": po_id, "tranId": f"PO{2000 + n}", "entity": {"id": vendor_id[po.vendor.key], "refName": po.vendor.name},
            "tranDate": po.po_date.isoformat(), "dueDate": po.schedule_date.isoformat(),
            "status": {"refName": STATUS[po.status]}, "approvalStatus": {"id": APPROVED, "refName": "Approved"},
            "otherRefNum": po.number, "subtotal": po.net_total, "taxTotal": po.tax_total, "total": po.grand_total,
            "lastModifiedDate": po.modified.isoformat(),
            "item": {"items": [{"line": i, "item": {"refName": line.item_code}, "description": line.item_name,
                                "units": line.uom, "quantity": line.qty, "rate": line.rate, "amount": line.amount,
                                "quantityReceived": po.received(i - 1), "taxRate1": line.tax_rate}
                               for i, line in enumerate(po.lines, start=1)]}})
        for receipt in po.receipts:
            receipt_no += 1
            docs["itemReceipt"].append({
                "id": str(1200 + receipt_no), "tranId": receipt.number, "entity": {"id": vendor_id[po.vendor.key]},
                "tranDate": receipt.posting_date.isoformat(), "createdFrom": {"id": po_id},
                "lastModifiedDate": receipt.modified.isoformat(),
                "item": {"items": [{"line": k, "orderLine": index + 1, "item": {"refName": po.lines[index].item_code},
                                    "quantity": qty}
                                   for k, (index, qty) in enumerate(receipt.quantities.items(), start=1)]}})
    return docs


def _matches(doc: dict[str, Any], q: str | None) -> bool:
    for clause in filter(None, re.split(r"\s+AND\s+", (q or "").strip())):
        if m := _IS.match(clause):
            if str(doc.get(m[1]) or "") != m[2].replace('\\"', '"').replace("\\\\", "\\"):
                return False
        elif m := _ANY.match(clause):
            wanted = {part.strip() for part in m[2].split(",")}
            value = doc.get(m[1])
            if (value.get("id") if isinstance(value, dict) else str(value)) not in wanted:
                return False
        else:
            raise ValueError(f"Unsupported query: {clause}")
    return True


class FakeNetSuite:
    def __init__(self, store: SimStore):
        self.data = Collections(store, render, id_field="id")

    def _find(self, record: str, ref: str) -> dict[str, Any] | None:
        if ref.startswith("eid:"):
            return next((d for d in self.data.all(record) if d.get("externalId") == ref[4:]), None)
        return self.data.get(record, ref)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path[len(RECORD) + 1:].split("/") if request.url.path.startswith(RECORD + "/") else []
        if not parts or parts[0] not in RECORDS:
            return _ns_error(404, "Record type not found")
        record, ref = parts[0], (parts[1] if len(parts) > 1 else None)
        if request.method == "GET" and ref is None:
            try:
                rows = [d for d in self.data.all(record) if _matches(d, request.url.params.get("q"))]
            except ValueError as exc:
                return _ns_error(400, str(exc))
            return json_reply(200, {"items": [{"id": d["id"], "links": []} for d in rows], "count": len(rows),
                                    "hasMore": False, "offset": 0, "totalResults": len(rows)})
        if request.method == "GET":
            doc = self._find(record, ref)
            return json_reply(200, doc) if doc else _ns_error(404, f"Record {ref} was not found")
        if request.method == "PUT" and ref and ref.startswith("eid:") and record in ("vendorBill", "purchaseOrder"):
            return self._upsert(record, ref[4:], load(request))
        return _ns_error(405, "Not supported by the simulated NetSuite")

    def _upsert(self, record: str, external_id: str, body: dict[str, Any]) -> httpx.Response:
        if self.data.get("vendor", (body.get("entity") or {}).get("id", "")) is None:
            return _ns_error(400, f"Invalid entity reference key {(body.get('entity') or {}).get('id')}.")
        items = {i["itemId"] for i in self.data.all("inventoryItem")}
        for line in (body.get("item") or {}).get("items", []):
            if (line.get("item") or {}).get("refName") not in items:
                return _ns_error(400, f"Invalid item reference key {(line.get('item') or {}).get('refName')}.")
        existing = self._find(record, f"eid:{external_id}")
        lines = [{**line, "line": n, "amount": str(Decimal(str(line["quantity"])) * Decimal(str(line["rate"])))}
                 for n, line in enumerate((body.get("item") or {}).get("items", []), start=1)]
        # Like NetSuite, totals are computed from the lines on save (tax comes from the account's tax setup).
        subtotal = sum((Decimal(line["amount"]) for line in lines), Decimal("0"))
        doc = {**(existing or {}), **body, "externalId": external_id, "item": {"items": lines},
               "subtotal": str(subtotal), "taxTotal": "0", "total": str(subtotal),
               "lastModifiedDate": datetime.now(UTC).isoformat()}
        if existing is None:
            doc["id"] = str(self.data.next_number(record, 3000))
            if record == "purchaseOrder":
                doc["tranId"] = f"PO{doc['id']}"
                doc["status"] = {"refName": "Pending Supervisor Approval"}
        self.data.put(record, doc)
        return httpx.Response(204, headers={"Location": f"https://sim.suitetalk.api.netsuite.com{RECORD}/{record}/{doc['id']}"})
