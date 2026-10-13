"""Oracle Fusion Cloud ERP adapter: simulated (BUILD_PLAN §4, §8; PROMPTS Step 19).

No free Fusion pod exists, so this connector runs against `oracle_fusion_sim.py` and is labelled Simulated.
Shapes follow /fscmRestApi/resources/11.13.18.05/<resource> (replies {"items": [...], "count", "hasMore",
"limit", "offset", "links"}; filters as `q=Field='value';Field2='value'`, REST framework version 1 query-by-example).

Mapping (checked 13 Oct where marked; the rest is unverified until a customer pod):
- vendor         = suppliers (SupplierNumber, Supplier, TaxpayerId = GSTIN, unverified);
- purchase order  = purchaseOrders?expand=lines (Status OPEN / CLOSED FOR RECEIVING / CLOSED);
- goods receipt   = receivingReceiptTransactions (TransactionType RECEIVE; resource name unverified);
- draft bill      = Payables `invoices` created through REST stay **unvalidated** until a person validates them;
                    lookup = q=InvoiceNumber='…';SupplierNumber='…' (filter pattern verified);
- draft PO        = draftPurchaseOrders (unverified), lookup = Description containing "orrfin:<key>".
Invoices and draft POs are created with their lines in one call (Fusion accepts child rows in the payload).
"""

import re
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
    ErpVendor,
    SeedReport,
)
from app.security.outbound import ErpHttp

API = "/fscmRestApi/resources/11.13.18.05"
ORRFIN_TAG = re.compile(r"orrfin:([0-9a-f]{64})")
STATUS = {"OPEN": "open", "CLOSED FOR RECEIVING": "to_bill", "CLOSED FOR INVOICING": "to_bill", "CLOSED": "closed",
          "FINALLY CLOSED": "closed"}


def oracle_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    return body.get("detail") or body.get("title") or response.text


def qbe(**conditions: str) -> str:
    """Query-by-example filter (framework v1): Field='value';Field2='value' with quotes doubled."""
    return ";".join(f"{field}='{str(value).replace(chr(39), chr(39) * 2)}'" for field, value in conditions.items())


def _dt(text: str | None) -> datetime:
    return datetime.fromisoformat((text or "2026-01-01T00:00:00+00:00").replace("Z", "+00:00"))


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class OracleFusionAdapter:
    def __init__(self, http: ErpHttp, *, business_unit: str = "Orrfin Demo BU"):
        self.http = http
        self.http.describe_error = oracle_error
        self.business_unit = business_unit

    def _items(self, resource: str, q: str | None = None, expand: str | None = None) -> list[dict[str, Any]]:
        """All rows, following hasMore/offset paging."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params = {"limit": "500", "offset": str(offset), "onlyData": "true"}
            if q:
                params["q"] = q
            if expand:
                params["expand"] = expand
            body = self.http.request("GET", f"{API}/{resource}", params=params,
                                     headers={"REST-Framework-Version": "1"}).json()
            page = body.get("items", [])
            rows += page
            if not body.get("hasMore") or not page:
                return rows
            offset += len(page)

    def _post(self, resource: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("POST", f"{API}/{resource}", json=body,
                                 headers={"Content-Type": "application/vnd.oracle.adf.resourceitem+json"}).json()

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated", draft_bill_means="Payables invoice, not yet validated",
                            draft_po_means="draft purchase order (not submitted)")

    def test_connection(self) -> ConnectionCheck:
        suppliers = self._items("suppliers")
        return ConnectionCheck(ok=True, steps=[CheckStep(name="Simulated Oracle Fusion", ok=True,
                                                         detail=f"{len(suppliers)} suppliers.")])

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for s in self._items("suppliers"):
            gstin = (s.get("TaxpayerId") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=str(s["SupplierNumber"]), name=s.get("Supplier") or "", gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=_dt(s.get("LastUpdateDate"))))
        return out

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        out = []
        for po in self._items("purchaseOrders", expand="lines"):
            number = po["OrderNumber"]
            lines = [ErpPoLine(
                erp_ref=f"{number}/{ln['LineNumber']}", line_no=int(ln["LineNumber"]), item_code=ln.get("Item") or "",
                description=ln.get("Description") or "", hsn=None, uom=ln.get("UOM"), qty=_dec(ln.get("Quantity")),
                rate=_dec(ln.get("Price")), amount=_dec(ln.get("Amount")), tax_rate=_dec(ln.get("TaxRate")))
                for ln in po.get("lines") or []]
            tag = ORRFIN_TAG.search(po.get("Description") or "")
            out.append(ErpPurchaseOrder(
                erp_ref=number, vendor_ref=str(po.get("SupplierNumber") or ""), po_date=_d(po.get("OrderDate")),
                schedule_date=_d(po.get("RequestedDeliveryDate")), status=STATUS.get(po.get("Status") or "", "open"),
                currency=po.get("CurrencyCode") or "INR", net_total=_dec(po.get("Ordered")),
                tax_total=_dec(po.get("TotalTax")), grand_total=_dec(po.get("Total")),
                orrfin_ref=tag.group(1) if tag else None, modified=_dt(po.get("LastUpdateDate")), lines=lines,
                po_number=po.get("SupplierOrder") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        vendor_of = {po["OrderNumber"]: str(po.get("SupplierNumber") or "") for po in self._items("purchaseOrders")}
        receipts: dict[str, ErpReceipt] = {}
        for r in self._items("receivingReceiptTransactions"):
            if r.get("TransactionType") != "RECEIVE":
                continue
            receipt = receipts.setdefault(r["ReceiptNumber"], ErpReceipt(
                erp_ref=r["ReceiptNumber"], vendor_ref=vendor_of.get(r["DocumentNumber"], ""),
                posting_date=_d(r.get("TransactionDate")), status="received", modified=_dt(r.get("TransactionDate")),
                lines=[]))
            receipt.lines.append(ErpReceiptLine(
                erp_ref=f"{r['ReceiptNumber']}/{r['ReceiptLineNumber']}", item_code=r.get("ItemNumber") or "",
                qty_received=_dec(r.get("Quantity")), po_ref=r["DocumentNumber"],
                po_line_ref=f"{r['DocumentNumber']}/{r['DocumentLineNumber']}"))
        return list(receipts.values())

    def create_draft_bill(self, bill: DraftBill) -> Created:
        doc = self._post("invoices", {
            "InvoiceNumber": bill.supplier_invoice_no, "SupplierNumber": bill.vendor_ref,
            "BusinessUnit": self.business_unit, "InvoiceAmount": _num(bill.grand_total),
            "InvoiceCurrency": bill.currency, "InvoiceDate": bill.invoice_date.isoformat(),
            "Description": f"orrfin:{bill.idempotency_key}",
            "invoiceLines": [{"LineNumber": n, "LineAmount": _num(line.amount), "Description": line.description,
                              "PurchaseOrderNumber": bill.po_ref, "Quantity": _num(line.qty),
                              "UnitPrice": _num(line.rate), "Item": line.item_code}
                             for n, line in enumerate(bill.lines, start=1)]})
        return Created(erp_doc_name=f"Invoice {doc['InvoiceId']}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._items("invoices", q=qbe(InvoiceNumber=supplier_invoice_no, SupplierNumber=vendor_ref))
        return f"Invoice {rows[0]['InvoiceId']}" if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        doc = self._post("draftPurchaseOrders", {
            "SupplierNumber": po.vendor_ref, "ProcurementBU": self.business_unit, "CurrencyCode": po.currency,
            "Description": f"orrfin:{po.idempotency_key} | {po.request_number}",
            "lines": [{"LineNumber": n, "Item": line.item_code, "Description": line.description,
                       "Quantity": _num(line.qty), "Price": _num(line.rate),
                       "RequestedDeliveryDate": po.schedule_date.isoformat()} for n, line in enumerate(po.lines, start=1)]})
        return Created(erp_doc_name=doc["OrderNumber"])

    def find_po(self, orrfin_key: str) -> str | None:
        rows = [r for r in self._items("draftPurchaseOrders") if f"orrfin:{orrfin_key}" in (r.get("Description") or "")]
        return rows[0]["OrderNumber"] if rows else None

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={},
                          notes=["Oracle Fusion is simulated: its data comes from the canonical dataset."])
