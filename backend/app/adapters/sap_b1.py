"""SAP Business One adapter, Service Layer: simulated (BUILD_PLAN §4, §8; PROMPTS Step 18).

SAP Business One has no free test system (partner demo licence only), so this connector runs against
`sap_b1_sim.py` and is labelled Simulated. Service Layer basics: POST /b1s/v1/Login {CompanyDB, UserName,
Password} returns a B1SESSION cookie; collections answer {"value": [...]} with OData $filter.

Mapping:
- vendor         = BusinessPartners with CardType cSupplier (FederalTaxID = GSTIN);
- purchase order  = PurchaseOrders (DocumentStatus bost_Open / bost_Close; NumAtCard = the PO number the
                    vendor quotes) with DocumentLines;
- goods receipt   = PurchaseDeliveryNotes ("Goods Receipt PO"), lines linked by BaseType 22 + BaseEntry + BaseLine;
- draft bill      = Drafts with DocObjectCode oPurchaseInvoices; lookup = CardCode + NumAtCard;
- draft PO        = Drafts with DocObjectCode oPurchaseOrders; lookup = Comments "orrfin:<key>".
"""

import re
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

PO_OBJECT = 22  # BaseType of a purchase order in B1
ORRFIN_TAG = re.compile(r"orrfin:([0-9a-f]{64})")


def b1_error(response: httpx.Response) -> str:
    error = (response.json() or {}).get("error") or {}
    message = error.get("message")
    return (message.get("value") if isinstance(message, dict) else message) or response.text


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text else None


def _modified(doc: dict[str, Any]) -> datetime:
    stamp = f"{doc.get('UpdateDate') or '2026-01-01'}T{doc.get('UpdateTime') or '00:00:00'}"
    return datetime.fromisoformat(stamp[:19]).replace(tzinfo=IST)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _tax(code: str | None) -> Decimal:
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    return Decimal(digits) if digits else Decimal("0")


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class SapB1Adapter:
    def __init__(self, http: ErpHttp, *, company_db: str, user: str, password: str):
        self.http = http
        self.http.describe_error = b1_error
        self.company_db, self.user, self.password = company_db, user, password
        self._logged_in = False

    def _login(self) -> None:
        if not self._logged_in:
            self.http.request("POST", "/Login", json={"CompanyDB": self.company_db, "UserName": self.user,
                                                      "Password": self.password})
            self._logged_in = True  # httpx keeps the B1SESSION cookie on the client

    def _list(self, entity: str, flt: str | None = None) -> list[dict[str, Any]]:
        self._login()
        params = {"$filter": flt} if flt else {}
        return self.http.request("GET", f"/{entity}", params=params).json()["value"]

    def _post(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        self._login()
        return self.http.request("POST", f"/{entity}", json=body).json()

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated", draft_bill_means="draft A/P invoice (Drafts, not added)",
                            draft_po_means="draft purchase order (Drafts, not added)")

    def test_connection(self) -> ConnectionCheck:
        partners = self._list("BusinessPartners")
        return ConnectionCheck(ok=True, steps=[CheckStep(name="Simulated SAP Business One", ok=True,
                                                         detail=f"Signed in; {len(partners)} business partners.")])

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for bp in self._list("BusinessPartners", "CardType eq 'cSupplier'"):
            gstin = (bp.get("FederalTaxID") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=bp["CardCode"], name=bp.get("CardName") or bp["CardCode"], gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=_modified(bp)))
        return out

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        received: dict[tuple[int, int], Decimal] = {}
        for note in self._list("PurchaseDeliveryNotes"):
            for line in note.get("DocumentLines") or []:
                if line.get("BaseType") == PO_OBJECT:
                    key = (int(line["BaseEntry"]), int(line["BaseLine"]))
                    received[key] = received.get(key, Decimal("0")) + _dec(line.get("Quantity"))
        out = []
        for po in self._list("PurchaseOrders"):
            entry = int(po["DocEntry"])
            doc_lines = po.get("DocumentLines") or []
            lines = [ErpPoLine(
                erp_ref=f"{entry}/{ln['LineNum']}", line_no=int(ln["LineNum"]) + 1, item_code=ln.get("ItemCode") or "",
                description=ln.get("ItemDescription") or "", hsn=None, uom=ln.get("MeasureUnit"),
                qty=_dec(ln.get("Quantity")), rate=_dec(ln.get("UnitPrice")), amount=_dec(ln.get("LineTotal")),
                tax_rate=_tax(ln.get("TaxCode"))) for ln in doc_lines]
            done = bool(lines) and all(received.get((entry, int(ln["LineNum"])), Decimal("0")) >= _dec(ln.get("Quantity"))
                                       for ln in doc_lines)
            status = "closed" if po.get("DocumentStatus") == "bost_Close" else ("to_bill" if done else "open")
            tag = ORRFIN_TAG.search(po.get("Comments") or "")
            vat = _dec(po.get("VatSum"))
            out.append(ErpPurchaseOrder(
                erp_ref=str(po["DocNum"]), vendor_ref=po.get("CardCode") or "", po_date=_d(po.get("DocDate")),
                schedule_date=_d(po.get("DocDueDate")), status=status, currency=po.get("DocCurrency") or "INR",
                net_total=_dec(po.get("DocTotal")) - vat, tax_total=vat, grand_total=_dec(po.get("DocTotal")),
                orrfin_ref=tag.group(1) if tag else None, modified=_modified(po), lines=lines,
                po_number=po.get("NumAtCard") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        out = []
        for note in self._list("PurchaseDeliveryNotes"):
            lines = []
            for ln in note.get("DocumentLines") or []:
                from_po = ln.get("BaseType") == PO_OBJECT
                lines.append(ErpReceiptLine(
                    erp_ref=f"{note['DocEntry']}/{ln['LineNum']}", item_code=ln.get("ItemCode") or "",
                    qty_received=_dec(ln.get("Quantity")), po_ref=str(ln.get("BaseEntry")) if from_po else None,
                    po_line_ref=f"{ln['BaseEntry']}/{ln['BaseLine']}" if from_po else None))
            out.append(ErpReceipt(erp_ref=str(note["DocNum"]), vendor_ref=note.get("CardCode") or "",
                                  posting_date=_d(note.get("DocDate")), status="received", modified=_modified(note),
                                  lines=lines))
        return out

    def create_draft_bill(self, bill: DraftBill) -> Created:
        doc = self._post("Drafts", {
            "DocObjectCode": "oPurchaseInvoices", "CardCode": bill.vendor_ref, "NumAtCard": bill.supplier_invoice_no,
            "DocDate": bill.invoice_date.isoformat(), "Comments": f"orrfin:{bill.idempotency_key}",
            "DocumentLines": [{"ItemCode": line.item_code, "Quantity": _num(line.qty), "UnitPrice": _num(line.rate)}
                              for line in bill.lines]})
        return Created(erp_doc_name=f"Draft {doc['DocEntry']}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._list("Drafts", f"DocObjectCode eq 'oPurchaseInvoices' and CardCode eq {odata_quote(vendor_ref)} "
                                    f"and NumAtCard eq {odata_quote(supplier_invoice_no)}")
        return f"Draft {rows[0]['DocEntry']}" if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        doc = self._post("Drafts", {
            "DocObjectCode": "oPurchaseOrders", "CardCode": po.vendor_ref, "DocDate": po.po_date.isoformat(),
            "DocDueDate": po.schedule_date.isoformat(),
            "Comments": f"orrfin:{po.idempotency_key} | {po.request_number}",
            "DocumentLines": [{"ItemCode": line.item_code, "Quantity": _num(line.qty), "UnitPrice": _num(line.rate)}
                              for line in po.lines]})
        return Created(erp_doc_name=f"Draft {doc['DocEntry']}")

    def find_po(self, orrfin_key: str) -> str | None:
        rows = [d for d in self._list("Drafts", "DocObjectCode eq 'oPurchaseOrders'")
                if f"orrfin:{orrfin_key}" in (d.get("Comments") or "")]
        return f"Draft {rows[0]['DocEntry']}" if rows else None

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={},
                          notes=["SAP Business One is simulated: its data comes from the canonical dataset."])
