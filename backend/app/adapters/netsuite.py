"""Oracle NetSuite adapter, SuiteTalk REST: simulated (BUILD_PLAN §4, §8; PROMPTS Step 19).

No free NetSuite account exists (customer sandboxes only), so this connector runs against `netsuite_sim.py`
and is labelled Simulated. Shapes follow /services/rest/record/v1/<record>: a list returns
{"items": [{"id", "links"}], "hasMore", ...} and each record is read on its own, with sublists as
{"items": [...]}; filters use `q=field IS "value" AND entity ANY_OF [id]`.

NetSuite has **native idempotency**: `PUT /record/v1/vendorBill/eid:<external id>` creates or updates the
record with that external ID, so with externalId = Orrfin's idempotency key a retry cannot make a second bill
(the strongest safety net among the connectors; upsert behaviour from third-party docs, unverified).
- vendor         = vendor (companyName, taxIdNum = GSTIN);
- purchase order  = purchaseOrder (approvalStatus Approved), otherRefNum = the PO number the vendor quotes;
- goods receipt   = itemReceipt (createdFrom = the PO, orderLine = the PO line);
- draft bill      = vendorBill with approvalStatus "Pending Approval"; lookup = tranId + entity;
- draft PO        = purchaseOrder "Pending Supervisor Approval"; lookup = GET purchaseOrder/eid:<key>.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpPoLine,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpReceiptLine,
    ErpRejected,
    ErpVendor,
    SeedReport,
)
from app.security.outbound import ErpHttp

RECORD = "/services/rest/record/v1"
PENDING_APPROVAL = "1"
APPROVED = "2"


def netsuite_error(response: httpx.Response) -> str:
    body = response.json()
    details = body.get("o:errorDetails") or []
    return "; ".join(d.get("detail", "") for d in details) or body.get("title") or response.text


def _dt(text: str | None) -> datetime:
    return datetime.fromisoformat((text or "2026-01-01T00:00:00+00:00").replace("Z", "+00:00"))


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


def _quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class NetSuiteAdapter:
    def __init__(self, http: ErpHttp):
        self.http = http
        self.http.describe_error = netsuite_error

    def _ids(self, record: str, q: str | None = None) -> list[str]:
        params = {"limit": "1000"}
        if q:
            params["q"] = q
        return [row["id"] for row in self.http.request("GET", f"{RECORD}/{record}", params=params).json()["items"]]

    def _get(self, record: str, ref: str) -> dict[str, Any] | None:
        try:
            return self.http.request("GET", f"{RECORD}/{record}/{ref}", params={"expandSubResources": "true"}).json()
        except ErpRejected as exc:
            if exc.status == 404:
                return None
            raise

    def _all(self, record: str, q: str | None = None) -> list[dict[str, Any]]:
        return [doc for doc in (self._get(record, i) for i in self._ids(record, q)) if doc]

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated", draft_bill_means="vendor bill pending approval",
                            draft_po_means="purchase order pending supervisor approval")

    def test_connection(self) -> ConnectionCheck:
        vendors = self._ids("vendor")
        return ConnectionCheck(ok=True, steps=[CheckStep(name="Simulated NetSuite", ok=True,
                                                         detail=f"{len(vendors)} vendors.")])

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for v in self._all("vendor"):
            gstin = (v.get("taxIdNum") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=str(v["id"]), name=v.get("companyName") or v.get("entityId") or "",
                                 gstin=gstin, state_code=gstin[:2] if gstin else None,
                                 modified=_dt(v.get("lastModifiedDate"))))
        return out

    def _orders(self) -> list[dict[str, Any]]:
        return [po for po in self._all("purchaseOrder")
                if (po.get("approvalStatus") or {}).get("id") != PENDING_APPROVAL]

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        out = []
        for po in self._orders():
            items = (po.get("item") or {}).get("items", [])
            lines = [ErpPoLine(
                erp_ref=f"{po['id']}/{it['line']}", line_no=int(it["line"]),
                item_code=(it.get("item") or {}).get("refName", ""), description=it.get("description") or "", hsn=None,
                uom=it.get("units"), qty=_dec(it.get("quantity")), rate=_dec(it.get("rate")),
                amount=_dec(it.get("amount")), tax_rate=_dec(it.get("taxRate1"))) for it in items]
            received_all = bool(items) and all(_dec(it.get("quantityReceived")) >= _dec(it.get("quantity")) for it in items)
            closed = (po.get("status") or {}).get("refName") == "Closed"
            external = po.get("externalId") or ""
            out.append(ErpPurchaseOrder(
                erp_ref=str(po.get("tranId") or po["id"]), vendor_ref=str((po.get("entity") or {}).get("id", "")),
                po_date=_d(po.get("tranDate")), schedule_date=_d(po.get("dueDate")),
                status="closed" if closed else ("to_bill" if received_all else "open"), currency="INR",
                net_total=_dec(po.get("subtotal")), tax_total=_dec(po.get("taxTotal")), grand_total=_dec(po.get("total")),
                orrfin_ref=external if len(external) == 64 else None, modified=_dt(po.get("lastModifiedDate")),
                lines=lines, po_number=po.get("otherRefNum") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        out = []
        for r in self._all("itemReceipt"):
            po_id = str((r.get("createdFrom") or {}).get("id", ""))
            out.append(ErpReceipt(
                erp_ref=str(r.get("tranId") or r["id"]), vendor_ref=str((r.get("entity") or {}).get("id", "")),
                posting_date=_d(r.get("tranDate")), status="received", modified=_dt(r.get("lastModifiedDate")),
                lines=[ErpReceiptLine(erp_ref=f"{r['id']}/{it['line']}",
                                      item_code=(it.get("item") or {}).get("refName", ""),
                                      qty_received=_dec(it.get("quantity")), po_ref=po_id,
                                      po_line_ref=f"{po_id}/{it['orderLine']}")
                       for it in (r.get("item") or {}).get("items", [])]))
        return out

    def _upsert(self, record: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
        self.http.request("PUT", f"{RECORD}/{record}/eid:{key}", json=body)
        doc = self._get(record, f"eid:{key}")
        if doc is None:
            raise ErpRejected(f"NetSuite accepted the {record} but it can't be read back.")
        return doc

    def create_draft_bill(self, bill: DraftBill) -> Created:
        doc = self._upsert("vendorBill", bill.idempotency_key, {
            "entity": {"id": bill.vendor_ref}, "tranId": bill.supplier_invoice_no,
            "tranDate": bill.invoice_date.isoformat(), "approvalStatus": {"id": PENDING_APPROVAL},
            "memo": "Draft from Orrfin",
            "item": {"items": [{"item": {"refName": line.item_code}, "quantity": _num(line.qty), "rate": _num(line.rate),
                                "description": line.description} for line in bill.lines]}})
        return Created(erp_doc_name=f"Bill {doc['id']}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        ids = self._ids("vendorBill", f"tranId IS {_quote(supplier_invoice_no)} AND entity ANY_OF [{vendor_ref}]")
        return f"Bill {ids[0]}" if ids else None

    def create_draft_po(self, po: DraftPo) -> Created:
        doc = self._upsert("purchaseOrder", po.idempotency_key, {
            "entity": {"id": po.vendor_ref}, "tranDate": po.po_date.isoformat(), "dueDate": po.schedule_date.isoformat(),
            "approvalStatus": {"id": PENDING_APPROVAL}, "memo": f"Draft PO from Orrfin for {po.request_number}",
            "item": {"items": [{"item": {"refName": line.item_code}, "quantity": _num(line.qty), "rate": _num(line.rate),
                                "description": line.description} for line in po.lines]}})
        return Created(erp_doc_name=str(doc.get("tranId") or doc["id"]))

    def find_po(self, orrfin_key: str) -> str | None:
        doc = self._get("purchaseOrder", f"eid:{orrfin_key}")
        return str(doc.get("tranId") or doc["id"]) if doc else None

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={},
                          notes=["NetSuite is simulated: its data comes from the canonical dataset."])
