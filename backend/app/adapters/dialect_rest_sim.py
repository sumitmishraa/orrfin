"""A simulated server for every ERP in `dialects.py`, in-process via httpx.MockTransport (PROMPTS Step 36).

It renders the canonical dataset in the ERP's own resource and field names, answers GET with the ERP's
list envelope, and accepts POSTs only for draft bills and draft POs. Like a real ERP it refuses a draft
for an unknown vendor or item (400), so the adapter's error handling is exercised too.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.dialect_rest import dig, plant
from app.adapters.dialects import Dialect
from app.adapters.sim_rest import Collections, json_error, json_reply, load
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

ID = "_id"


def render(d: Dialect):
    def build() -> dict[str, list[dict[str, Any]]]:
        f, data = d.f, dataset()
        docs: dict[str, list[dict[str, Any]]] = {logical: [] for logical in d.collections}
        stamp = datetime(2026, 9, 1, 9, 30).isoformat()
        for v in data.vendors:
            doc = {ID: v.key}
            for path, value in ((f["vendor_id"], v.key), (f["vendor_name"], v.name), (f["vendor_tax"], v.gstin),
                                (f["modified"], v.modified.isoformat()[:19])):
                plant(doc, path, value)
            docs["vendors"].append(doc)
        for n, po in enumerate(data.purchase_orders, start=1):
            po_id = f"{n:04d}"
            lines = []
            for i, line in enumerate(po.lines, start=1):
                row: dict[str, Any] = {}
                for path, value in ((f["line_id"], str(i)), (f["line_item"], line.item_code), (f["line_desc"], line.item_name),
                                    (f["line_qty"], line.qty), (f["line_rate"], line.rate), (f["line_amount"], line.amount),
                                    (f["line_tax"], Decimal(d.tax_percent) if d.tax_percent else line.tax_rate)):
                    plant(row, path, value)
                lines.append(row)
            doc = {ID: po_id}
            for path, value in ((f["po_id"], po_id), (f["po_number"], po.number), (f["po_vendor"], po.vendor.key),
                                (f["po_date"], po.po_date.isoformat()), (f["po_due"], po.schedule_date.isoformat()),
                                (f["po_status"], d.closed_value if po.closed else d.open_value), (f["po_memo"], ""),
                                (f["modified"], stamp), (f["po_lines"], lines)):
                plant(doc, path, value)
            docs["pos"].append(doc)
            if "receipts" not in d.collections:
                continue
            for k, receipt in enumerate(po.receipts, start=1):
                rc_id = f"{n:04d}-{k}"
                rc_lines = []
                for j, (index, qty) in enumerate(receipt.quantities.items(), start=1):
                    row = {}
                    for path, value in ((f["rc_line_id"], str(j)), (f["rc_item"], po.lines[index].item_code),
                                        (f["rc_qty"], qty), (f["rc_po"], po_id), (f["rc_po_line"], str(index + 1))):
                        plant(row, path, value)
                    rc_lines.append(row)
                note = {ID: rc_id}
                for path, value in ((f["rc_id"], rc_id), (f["rc_vendor"], po.vendor.key),
                                    (f["rc_date"], receipt.posting_date.isoformat()), (f["modified"], stamp),
                                    (f["rc_lines"], rc_lines)):
                    plant(note, path, value)
                docs["receipts"].append(note)
        docs.pop("po_drafts", None)  # drafts live in the pos collection (or the bills one); nothing to render
        return docs
    return build


class FakeDialectServer:
    def __init__(self, dialect: Dialect, store: SimStore):
        self.d = dialect
        self.data = Collections(store, render(dialect), id_field=ID)
        self.by_resource = {resource: logical for logical, resource in dialect.collections.items() if logical != "po_drafts"}
        self.prefix = httpx.URL(dialect.base_url).path.rstrip("/")

    def _reply_list(self, resource: str, rows: list[dict[str, Any]]) -> httpx.Response:
        if not self.d.envelope:
            return json_reply(200, rows)
        envelope: dict[str, Any] = {}
        plant(envelope, self.d.envelope.format(c=resource.split("/")[-1]), rows)
        return json_reply(200, envelope)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        resource = request.url.path[len(self.prefix):].strip("/")
        logical = self.by_resource.get(resource)
        if logical is None:
            return json_error(404, "NotFound", f"Unknown resource {resource}")
        if request.method == "GET":
            return self._reply_list(resource, self.data.all(logical))
        if request.method != "POST" or logical not in ("bills", "pos"):
            return json_error(405, "NotAllowed", "Only draft bills and draft purchase orders can be created through Orrfin")
        f, body = self.d.f, load(request)
        status_path = f["bill_status"] if logical == "bills" else f["po_status"]
        if dig(body, status_path) != self.d.draft_value:
            return json_error(400, "NotDraft", "Orrfin may only create drafts")
        vendor_path = f["bill_vendor"] if logical == "bills" else f["po_vendor"]
        if dig(body, vendor_path) not in {dig(v, f["vendor_id"]) for v in self.data.all("vendors")}:
            return json_error(400, "InvalidVendor", f"Unknown vendor {dig(body, vendor_path)!r}")
        items = {dig(l, f["line_item"]) for po in self.data.all("pos") for l in dig(po, f["po_lines"]) or []}
        for line in dig(body, f["bill_lines"] if logical == "bills" else f["po_lines"]) or []:
            if dig(line, f["line_item"]) not in items:
                return json_error(400, "InvalidItem", f"Unknown item {dig(line, f['line_item'])!r}")
        number = self.data.next_number(f"{self.d.system}-{logical}", 9001)
        id_path = f["bill_id"] if logical == "bills" else f["po_id"]
        plant(body, id_path, str(number))
        body[ID] = str(number)
        return json_reply(201, self.data.put(logical, body))
