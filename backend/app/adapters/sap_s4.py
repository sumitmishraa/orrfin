"""SAP S/4HANA Cloud adapter: Sandbox reads + simulated writes (BUILD_PLAN §2, §8; PROMPTS Step 18).

Reads use SAP's OData V2 APIs ({"d": {"results": [...]}}, dates as "/Date(ms)/", decimals as strings):
- vendor         = API_BUSINESS_PARTNER / A_Supplier (TaxNumber3 = GSTIN in Indian setups; sandbox data has none);
- purchase order  = API_PURCHASEORDER_PROCESS_SRV / A_PurchaseOrder + to_PurchaseOrderItem (V2, marked
                    deprecated in favour of a V4 PO API; still served by the sandbox, unverified for how long);
- goods receipt   = API_MATERIAL_DOCUMENT_SRV / A_MaterialDocumentHeader + to_MaterialDocumentItem,
                    movement type 101, linked by PurchaseOrder + PurchaseOrderItem.
In **Sandbox** mode the reads go to sandbox.api.sap.com with the founder's `APIKey` and return SAP's own sample
data (not the demo dataset), so demo invoices won't match there. SAP's sandbox is read-only, so **writes are
always simulated** (a separate simulated store), and the UI says so.

Writes (simulated):
- draft bill = **parked** supplier invoice (API_SUPPLIERINVOICE_PROCESS_SRV / A_SupplierInvoice; how parking is
  flagged through the API is unverified); lookup = InvoicingParty + SupplierInvoiceIDByInvcgParty (16 chars);
- draft PO   = **purchase requisition** (API_PURCHASEREQ_PROCESS_SRV), because the released APIs have no draft PO
  (BUILD_PLAN §8 design choice); lookup = PurReqnDescription "ORF-<key prefix>" (40 characters max).
Writes fetch an x-csrf-token first, as SAP requires.
"""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_rest import odata_quote
from app.erp_demo.canonical import IST
from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpError,
    ErpPoLine,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpReceiptLine,
    ErpVendor,
    Label,
    SeedReport,
)
from app.security.outbound import ErpHttp

ODATA = "/sap/opu/odata/sap"
SANDBOX_HOST = "https://sandbox.api.sap.com/s4hanacloud"
DRAFT_TAG = "ORF-"
KEY_PREFIX = 20
FIXED_MODIFIED = datetime(2026, 9, 18, 10, 0, tzinfo=IST)
_DATE = re.compile(r"/Date\((-?\d+)")
CENT = Decimal("0.01")


def sap_error(response: httpx.Response) -> str:
    error = (response.json() or {}).get("error") or {}
    message = error.get("message")
    return (message.get("value") if isinstance(message, dict) else message) or response.text


def sap_date(text: str | None) -> date | None:
    m = _DATE.search(text or "")
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=UTC).date() if m else None


def to_sap_date(value: date) -> str:
    return f"/Date({int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)})/"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def _tax(code: str | None) -> Decimal:
    # Demo tax codes are "G18"-style; real SAP codes (V1, I1, …) need the customer's tax-code table.
    m = re.fullmatch(r"G(\d+)", code or "")
    return Decimal(m.group(1)) if m else Decimal("0")


class SapS4Adapter:
    contract_gaps = {"closed_status"}  # completion flags differ per SAP setup; the demo maps no "closed"

    def __init__(self, read: ErpHttp, write: ErpHttp, *, label: Label, top: int | None = None):
        self.read = read
        self.write = write
        for http in (read, write):
            http.describe_error = sap_error
        self.label = label
        self.top = top  # the public sandbox holds thousands of sample rows; read one page of them

    def _get(self, service: str, entity: str, flt: str | None = None, expand: str | None = None,
             http: ErpHttp | None = None) -> list[dict[str, Any]]:
        params = {"$format": "json"}
        if flt:
            params["$filter"] = flt
        if expand:
            params["$expand"] = expand
        if self.top and http is None:
            params["$top"] = str(self.top)
        body = (http or self.read).request("GET", f"{ODATA}/{service}/{entity}", params=params).json()
        return body["d"]["results"]

    def _post(self, service: str, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = self.write.request("GET", f"{ODATA}/{service}/", headers={"x-csrf-token": "Fetch"}) \
            .headers.get("x-csrf-token", "")
        return self.write.request("POST", f"{ODATA}/{service}/{entity}", json=payload,
                                  headers={"x-csrf-token": token}).json()["d"]

    def capabilities(self) -> Capabilities:
        note = "SAP's sandbox is read-only, so drafts go to Orrfin's simulated SAP." if self.label == "sandbox" else ""
        return Capabilities(label=self.label, draft_bill_means="parked supplier invoice",
                            draft_po_means="purchase requisition (SAP's APIs have no draft PO)", write_note=note)

    def test_connection(self) -> ConnectionCheck:
        try:
            suppliers = self._get("API_BUSINESS_PARTNER", "A_Supplier")
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(name="Read SAP suppliers", ok=False, detail=str(exc))])
        steps = [CheckStep(name="Read SAP suppliers", ok=True, detail=f"{len(suppliers)} suppliers read.")]
        if self.label == "sandbox":
            steps.append(CheckStep(name="Write-back", ok=True,
                                   detail="Simulated: SAP's sandbox is read-only and holds SAP's sample data."))
        return ConnectionCheck(ok=True, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for s in self._get("API_BUSINESS_PARTNER", "A_Supplier"):
            gstin = (s.get("TaxNumber3") or "").strip().upper() or None
            if gstin and len(gstin) != 15:
                gstin = None  # TaxNumber3 means other things outside India
            out.append(ErpVendor(erp_ref=s["Supplier"], name=s.get("SupplierName") or s["Supplier"], gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=FIXED_MODIFIED))
        return out

    def _receipt_rows(self) -> list[dict[str, Any]]:
        return self._get("API_MATERIAL_DOCUMENT_SRV", "A_MaterialDocumentHeader", expand="to_MaterialDocumentItem")

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        received: dict[tuple[str, str], Decimal] = {}
        for header in self._receipt_rows():
            for item in (header.get("to_MaterialDocumentItem") or {}).get("results", []):
                if item.get("GoodsMovementType") == "101" and item.get("PurchaseOrder"):
                    key = (item["PurchaseOrder"], str(item.get("PurchaseOrderItem")))
                    received[key] = received.get(key, Decimal("0")) + _dec(item.get("QuantityInEntryUnit"))
        out = []
        for po in self._get("API_PURCHASEORDER_PROCESS_SRV", "A_PurchaseOrder", expand="to_PurchaseOrderItem"):
            number = po["PurchaseOrder"]
            items = (po.get("to_PurchaseOrderItem") or {}).get("results", [])
            lines = []
            for i, item in enumerate(items, start=1):
                qty = _dec(item.get("OrderQuantity"))
                per = _dec(item.get("NetPriceQuantity")) or Decimal("1")
                price = _dec(item.get("NetPriceAmount")) / per
                lines.append(ErpPoLine(
                    erp_ref=f"{number}/{item['PurchaseOrderItem']}", line_no=i, item_code=item.get("Material") or "",
                    description=item.get("PurchaseOrderItemText") or "", hsn=None,
                    uom=item.get("PurchaseOrderQuantityUnit"), qty=qty, rate=price.quantize(CENT),
                    amount=(qty * price).quantize(CENT), tax_rate=_tax(item.get("TaxCode"))))
            net = sum((l.amount for l in lines), Decimal("0"))
            tax = sum(((l.amount * l.tax_rate / 100).quantize(CENT) for l in lines), Decimal("0"))
            done = bool(lines) and all(received.get((number, str(item["PurchaseOrderItem"])), Decimal("0"))
                                       >= _dec(item.get("OrderQuantity")) for item in items)
            out.append(ErpPurchaseOrder(
                erp_ref=number, vendor_ref=po.get("Supplier") or "", po_date=sap_date(po.get("PurchaseOrderDate")),
                schedule_date=None, status="to_bill" if done else "open", currency=po.get("DocumentCurrency") or "INR",
                net_total=net, tax_total=tax, grand_total=net + tax, orrfin_ref=None, modified=FIXED_MODIFIED,
                lines=lines, po_number=po.get("CorrespncExternalReference") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        out = []
        for header in self._receipt_rows():
            items = [i for i in (header.get("to_MaterialDocumentItem") or {}).get("results", [])
                     if i.get("GoodsMovementType") == "101"]
            if not items:
                continue
            number = f"{header['MaterialDocument']}/{header['MaterialDocumentYear']}"
            out.append(ErpReceipt(
                erp_ref=number, vendor_ref=items[0].get("Supplier") or "", posting_date=sap_date(header.get("PostingDate")),
                status="received", modified=FIXED_MODIFIED,
                lines=[ErpReceiptLine(erp_ref=f"{number}/{i['MaterialDocumentItem']}", item_code=i.get("Material") or "",
                                      qty_received=_dec(i.get("QuantityInEntryUnit")), po_ref=i.get("PurchaseOrder"),
                                      po_line_ref=f"{i.get('PurchaseOrder')}/{i.get('PurchaseOrderItem')}")
                       for i in items]))
        return out

    def create_draft_bill(self, bill: DraftBill) -> Created:
        doc = self._post("API_SUPPLIERINVOICE_PROCESS_SRV", "A_SupplierInvoice", {
            "CompanyCode": "1710", "DocumentDate": to_sap_date(bill.invoice_date),
            "PostingDate": to_sap_date(bill.invoice_date), "InvoicingParty": bill.vendor_ref,
            "SupplierInvoiceIDByInvcgParty": bill.supplier_invoice_no[:16], "DocumentCurrency": bill.currency,
            "InvoiceGrossAmount": str(bill.grand_total), "SupplierInvoiceStatus": "A",  # A = parked (unverified)
            "DocumentHeaderText": f"orrfin:{bill.idempotency_key[:16]}",
            "to_SuppInvcItemPurOrdRef": {"results": [{
                "SupplierInvoiceItem": f"{n:06d}", "PurchaseOrder": bill.po_ref or "",
                "PurchaseOrderItem": (line.po_line_ref or "/").split("/")[-1], "DocumentCurrency": bill.currency,
                "SupplierInvoiceItemAmount": str(line.amount), "QuantityInPurchaseOrderUnit": str(line.qty)}
                for n, line in enumerate(bill.lines, start=1)]},
        })
        return Created(erp_doc_name=f"{doc['SupplierInvoice']}/{doc['FiscalYear']}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._get("API_SUPPLIERINVOICE_PROCESS_SRV", "A_SupplierInvoice",
                         f"InvoicingParty eq {odata_quote(vendor_ref)} and "
                         f"SupplierInvoiceIDByInvcgParty eq {odata_quote(supplier_invoice_no[:16])}", http=self.write)
        return f"{rows[0]['SupplierInvoice']}/{rows[0]['FiscalYear']}" if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        doc = self._post("API_PURCHASEREQ_PROCESS_SRV", "A_PurchaseRequisitionHeader", {
            "PurchaseRequisitionType": "NB",
            "PurReqnDescription": f"{DRAFT_TAG}{po.idempotency_key[:KEY_PREFIX].upper()}",
            "to_PurchaseReqnItem": {"results": [{
                "PurchaseRequisitionItem": f"{n * 10:05d}", "Material": line.item_code,
                "PurchaseRequisitionItemText": line.description[:40], "RequestedQuantity": str(line.qty),
                "PurchaseRequisitionPrice": str(line.rate), "FixedSupplier": po.vendor_ref,
                "DeliveryDate": to_sap_date(po.schedule_date)} for n, line in enumerate(po.lines, start=1)]},
        })
        return Created(erp_doc_name=doc["PurchaseRequisition"])

    def find_po(self, orrfin_key: str) -> str | None:
        tag = f"{DRAFT_TAG}{orrfin_key[:KEY_PREFIX].upper()}"
        rows = self._get("API_PURCHASEREQ_PROCESS_SRV", "A_PurchaseRequisitionHeader",
                         f"PurReqnDescription eq {odata_quote(tag)}", http=self.write)
        return rows[0]["PurchaseRequisition"] if rows else None

    def seed_demo_data(self) -> SeedReport:
        note = ("SAP's sandbox holds SAP's own sample data and is read-only: nothing to create."
                if self.label == "sandbox" else "Simulated SAP: its data comes from the canonical dataset.")
        return SeedReport(created={}, existing={}, notes=[note])
