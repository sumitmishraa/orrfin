"""Microsoft Dynamics 365 Finance & Operations adapter: simulated (BUILD_PLAN §4, §8; PROMPTS Step 17).

There is no free F&O system, so this connector runs against `dynamics_fo_sim.py`, fixtures in the shape of
F&O's OData data entities (`/data/<Entity>?$filter=...`, `{"value": [...]}`), and is labelled Simulated.
Going live needs a customer's tier-1 environment, an Entra app, and the "(unverified)" entity names below
checked against it (docs/ERP_CONNECTORS.md).

Mapping:
- vendor         = VendorsV2 (VendorAccountNumber, VendorOrganizationName, TaxExemptNumber = GSTIN);
- purchase order  = PurchaseOrderHeadersV2 + PurchaseOrderLinesV2; only DocumentApprovalStatus Confirmed /
                    Approved are mirrored (Draft = not yet a real order);
- goods receipt   = product receipt lines (ProductReceiptLines, entity name unverified);
- draft bill      = pending vendor invoice (VendorInvoiceHeaders + VendorInvoiceLines, not posted);
                    lookup = InvoiceAccount + InvoiceNumber;
- draft PO        = PurchaseOrderHeadersV2 in DocumentApprovalStatus Draft; lookup = VendorOrderReference
                    "ORF-<key prefix>" (reference field choice unverified).
Header and lines are separate calls, so a header found without lines is removed by the lookup (as for BC).
"""

from datetime import date, datetime
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
    ErpPoLine,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpReceiptLine,
    ErpVendor,
    SeedReport,
)
from app.security.outbound import ErpHttp

DATA_AREA = "orf"
DRAFT_TAG = "ORF-"
KEY_PREFIX = 20
FIXED_MODIFIED = datetime(2026, 9, 18, 10, 0, tzinfo=IST)  # data entities carry no last-modified stamp
CENT = Decimal("0.01")


def fo_error(response: httpx.Response) -> str:
    error = (response.json() or {}).get("error") or {}
    inner = (error.get("innererror") or {}).get("message", "")
    return f"{error.get('message', '')} {inner}".strip() or response.text


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text and not text.startswith("1900") else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _tax(group: str | None) -> Decimal:
    digits = "".join(ch for ch in (group or "") if ch.isdigit())
    return Decimal(digits) if digits else Decimal("0")


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class DynamicsFoAdapter:
    contract_gaps = {"closed_status"}  # F&O has no "closed but partly received" status in these entities

    def __init__(self, http: ErpHttp):
        self.http = http
        self.http.describe_error = fo_error

    def _list(self, entity: str, flt: str | None = None) -> list[dict[str, Any]]:
        params = {"cross-company": "true"}
        if flt:
            params["$filter"] = flt
        return self.http.request("GET", f"/{entity}", params=params).json()["value"]

    def _post(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("POST", f"/{entity}", json={"dataAreaId": DATA_AREA, **body}).json()

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated", draft_bill_means="pending vendor invoice (not posted)",
                            draft_po_means="purchase order in approval status Draft")

    def test_connection(self) -> ConnectionCheck:
        vendors = self._list("VendorsV2")
        return ConnectionCheck(ok=True, steps=[CheckStep(name="Simulated F&O", ok=True,
                                                         detail=f"{len(vendors)} vendors in the simulated entities.")])

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for v in self._list("VendorsV2"):
            gstin = (v.get("TaxExemptNumber") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=v["VendorAccountNumber"], name=v.get("VendorOrganizationName") or "",
                                 gstin=gstin, state_code=gstin[:2] if gstin else None, modified=FIXED_MODIFIED))
        return out

    def _orders(self) -> list[dict[str, Any]]:
        return [h for h in self._list("PurchaseOrderHeadersV2")
                if h.get("DocumentApprovalStatus") in ("Approved", "Confirmed")]

    def _received(self) -> dict[str, Decimal]:
        got: dict[str, Decimal] = {}
        for r in self._list("ProductReceiptLines"):
            key = f"{r['PurchaseOrderNumber']}/{r['PurchaseOrderLineNumber']}"
            got[key] = got.get(key, Decimal("0")) + _dec(r.get("ReceivedInventoryQuantity"))
        return got

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        lines = self._list("PurchaseOrderLinesV2")
        received = self._received()
        out = []
        for h in self._orders():
            number = h["PurchaseOrderNumber"]
            mine = sorted((ln for ln in lines if ln.get("PurchaseOrderNumber") == number),
                          key=lambda ln: int(ln["LineNumber"]))
            po_lines = [ErpPoLine(
                erp_ref=f"{number}/{ln['LineNumber']}", line_no=int(ln["LineNumber"]), item_code=ln.get("ItemNumber") or "",
                description=ln.get("LineDescription") or "", hsn=ln.get("HSNCode"), uom=ln.get("PurchaseUnitSymbol"),
                qty=_dec(ln.get("OrderedPurchaseQuantity")), rate=_dec(ln.get("PurchasePrice")),
                amount=_dec(ln.get("LineAmount")), tax_rate=_tax(ln.get("SalesTaxItemGroupCode"))) for ln in mine]
            net = sum((l.amount for l in po_lines), Decimal("0"))
            tax = sum(((l.amount * l.tax_rate / 100).quantize(CENT) for l in po_lines), Decimal("0"))
            done = bool(po_lines) and all(received.get(l.erp_ref, Decimal("0")) >= l.qty for l in po_lines)
            ref = str(h.get("VendorOrderReference") or "")
            out.append(ErpPurchaseOrder(
                erp_ref=number, vendor_ref=h.get("OrderVendorAccountNumber") or "", po_date=_d(h.get("AccountingDate")),
                schedule_date=_d(h.get("RequestedDeliveryDate")), status="to_bill" if done else "open",
                currency=h.get("CurrencyCode") or "INR", net_total=net, tax_total=tax, grand_total=net + tax,
                orrfin_ref=ref[len(DRAFT_TAG):].lower() if ref.startswith(DRAFT_TAG) else None,
                modified=FIXED_MODIFIED, lines=po_lines, po_number=None if ref.startswith(DRAFT_TAG) else ref or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        vendor_of = {h["PurchaseOrderNumber"]: h.get("OrderVendorAccountNumber") or "" for h in self._orders()}
        receipts: dict[str, ErpReceipt] = {}
        for r in self._list("ProductReceiptLines"):
            number = r["ProductReceiptNumber"]
            receipt = receipts.setdefault(number, ErpReceipt(
                erp_ref=number, vendor_ref=vendor_of.get(r["PurchaseOrderNumber"], ""),
                posting_date=_d(r.get("ProductReceiptDate")), status="received", modified=FIXED_MODIFIED, lines=[]))
            receipt.lines.append(ErpReceiptLine(
                erp_ref=f"{number}/{r['LineNumber']}", item_code=r.get("ItemNumber") or "",
                qty_received=_dec(r.get("ReceivedInventoryQuantity")), po_ref=r["PurchaseOrderNumber"],
                po_line_ref=f"{r['PurchaseOrderNumber']}/{r['PurchaseOrderLineNumber']}"))
        return list(receipts.values())

    def _complete_or_remove(self, header_entity: str, line_entity: str, key_field: str,
                            rows: list[dict[str, Any]]) -> str | None:
        """A header with no lines is an unfinished draft (reply lost between calls): remove it, report not found."""
        lines = self._list(line_entity)
        for row in rows:
            if any(ln.get(key_field) == row[key_field] for ln in lines):
                return row[key_field]
            self.http.request("DELETE", f"/{header_entity}(dataAreaId='{DATA_AREA}',"
                                        f"{key_field}={odata_quote(row[key_field])})")
        return None

    def create_draft_bill(self, bill: DraftBill) -> Created:
        reference = f"ORF-VI-{bill.idempotency_key[:12].upper()}"
        self._post("VendorInvoiceHeaders", {
            "HeaderReference": reference, "InvoiceAccount": bill.vendor_ref, "InvoiceNumber": bill.supplier_invoice_no,
            "InvoiceDate": bill.invoice_date.isoformat(), "PurchaseOrder": bill.po_ref or "",
            "InvoiceDescription": f"orrfin:{bill.idempotency_key}"})
        for n, line in enumerate(bill.lines, start=1):
            self._post("VendorInvoiceLines", {"HeaderReference": reference, "LineNumber": n,
                                              "ItemNumber": line.item_code, "ReceiveNow": _num(line.qty),
                                              "UnitPrice": _num(line.rate), "LineAmount": _num(line.amount)})
        return Created(erp_doc_name=reference)

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._list("VendorInvoiceHeaders", f"InvoiceAccount eq {odata_quote(vendor_ref)} and "
                                                  f"InvoiceNumber eq {odata_quote(supplier_invoice_no)}")
        return self._complete_or_remove("VendorInvoiceHeaders", "VendorInvoiceLines", "HeaderReference", rows)

    def create_draft_po(self, po: DraftPo) -> Created:
        number = f"ORF-PO-{po.idempotency_key[:10].upper()}"
        self._post("PurchaseOrderHeadersV2", {
            "PurchaseOrderNumber": number, "OrderVendorAccountNumber": po.vendor_ref,
            "AccountingDate": po.po_date.isoformat(), "RequestedDeliveryDate": po.schedule_date.isoformat(),
            "DocumentApprovalStatus": "Draft", "PurchaseOrderStatus": "Backorder", "CurrencyCode": po.currency,
            "VendorOrderReference": f"{DRAFT_TAG}{po.idempotency_key[:KEY_PREFIX].upper()}"})
        for n, line in enumerate(po.lines, start=1):
            self._post("PurchaseOrderLinesV2", {
                "PurchaseOrderNumber": number, "LineNumber": n, "ItemNumber": line.item_code,
                "LineDescription": line.description, "OrderedPurchaseQuantity": _num(line.qty),
                "PurchasePrice": _num(line.rate), "LineAmount": _num(line.amount)})
        return Created(erp_doc_name=number)

    def find_po(self, orrfin_key: str) -> str | None:
        tag = f"{DRAFT_TAG}{orrfin_key[:KEY_PREFIX].upper()}"
        rows = self._list("PurchaseOrderHeadersV2", f"VendorOrderReference eq {odata_quote(tag)}")
        return self._complete_or_remove("PurchaseOrderHeadersV2", "PurchaseOrderLinesV2", "PurchaseOrderNumber", rows)

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={},
                          notes=["Dynamics F&O is simulated: its data comes from the canonical dataset."])
