"""Microsoft Dynamics 365 Business Central adapter, API v2.0 (BUILD_PLAN §4, §8; PROMPTS Step 17).

Auth: Microsoft Entra client credentials (tenant, client id, client secret) → token from
login.microsoftonline.com with scope https://api.businesscentral.dynamics.com/.default; the token lives in
memory only. Base: https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/api/v2.0/companies({id}).

Mapping (docs/ERP_CONNECTORS.md; facts checked on learn.microsoft.com 12 Oct, gaps marked):
- vendor        = `vendors` (number, displayName, taxRegistrationNumber = GSTIN);
- purchase order = `purchaseOrders` + `purchaseOrderLines`; status Draft / In Review / Open (Open = released).
                   Orrfin's own unreleased drafts (vendorOrderNumber "ORF-…") are not mirrored until released;
- goods receipt  = the API doesn't link `purchaseReceipts` back to PO lines (unverified), so receipts are read
                   from each PO line's `receivedQuantity` (one receipt record per PO);
- draft bill     = unposted `purchaseInvoices` (+ lines); lookup = vendorNumber + vendorInvoiceNumber;
- draft PO       = `purchaseOrders` in status Draft (not released); lookup = vendorOrderNumber "ORF-<key prefix>"
                   (35 characters max, so the first 20 hex of the key; field choice unverified).
Known gaps (the contract suite skips them for a seeded BC): Business Central has no "closed" PO status in the
API, the standard API cannot post a receipt, and GST amounts come from BC's own tax setup.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_rest import odata_quote
from app.erp_demo.canonical import Dataset, dataset
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
    ErpRejected,
    ErpVendor,
    Label,
    SeedReport,
)
from app.security.outbound import ErpHttp

TOKEN_HOST = "https://login.microsoftonline.com"
API_HOST = "https://api.businesscentral.dynamics.com"
SCOPE = f"{API_HOST}/.default"
DRAFT_TAG = "ORF-"
KEY_PREFIX = 20  # vendorOrderNumber holds 35 characters


def bc_error(response: httpx.Response) -> str:
    body = response.json()
    error = body.get("error") or {}
    return f"{error.get('code', '')}: {error.get('message', '')}".strip(": ") or response.text


def _dt(text: str | None) -> datetime:
    return datetime.fromisoformat((text or "2026-01-01T00:00:00Z").replace("Z", "+00:00"))


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text and not text.startswith("0001") else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class BusinessCentralAdapter:
    contract_gaps = {"closed_status"}

    def __init__(self, api: ErpHttp, token_http: ErpHttp | None, *, tenant: str, client_id: str, client_secret: str,
                 company_name: str | None, label: Label):
        self.api = api
        self.api.describe_error = bc_error
        self.token_http = token_http
        self.tenant, self.client_id, self.client_secret = tenant, client_id, client_secret
        self.company_name = (company_name or "").strip() or None
        self.label = label
        self._token: str | None = None
        self._company_id: str | None = None

    # --- plumbing --------------------------------------------------------------------------------
    def _auth(self) -> None:
        if self._token or self.token_http is None:
            return
        response = self.token_http.request("POST", f"/{self.tenant}/oauth2/v2.0/token", data={
            "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret,
            "scope": SCOPE})
        self._token = response.json()["access_token"]
        self.api.secrets = (*self.api.secrets, self._token)
        self.api.client.headers["Authorization"] = f"Bearer {self._token}"

    def _call(self, method: str, path: str, **kwargs) -> Any:
        self._auth()
        response = self.api.request(method, path, **kwargs)
        return response.json() if response.content else None

    def _company(self) -> str:
        if self._company_id is None:
            companies = self._call("GET", "/companies")["value"]
            if self.company_name:
                match = [c for c in companies if (c.get("name") or "").lower() == self.company_name.lower()
                         or (c.get("displayName") or "").lower() == self.company_name.lower()]
            else:
                match = companies[:1] if len(companies) == 1 else []
            if not match:
                names = ", ".join(c.get("name", "") for c in companies) or "none"
                raise ErpRejected(f"Business Central company not found. Companies here: {names}. "
                                  "Enter the company name on the Connectors page.")
            self._company_id = match[0]["id"]
        return self._company_id

    def _list(self, entity: str, flt: str | None = None, expand: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if flt:
            params["$filter"] = flt
        if expand:
            params["$expand"] = expand
        return self._call("GET", f"/companies({self._company()})/{entity}", params=params)["value"]

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/companies({self._company()})/{path}", json=body)

    # --- port ------------------------------------------------------------------------------------
    def capabilities(self) -> Capabilities:
        return Capabilities(label=self.label, draft_bill_means="unposted Purchase Invoice",
                            draft_po_means="Purchase Order in status Open (not released)")

    def test_connection(self) -> ConnectionCheck:
        steps = []
        try:
            self._auth()
            steps.append(CheckStep(name="Sign in with Microsoft Entra", ok=True, detail="Token received."))
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(name="Sign in with Microsoft Entra", ok=False,
                                                              detail=str(exc))])
        except (KeyError, ValueError):
            return ConnectionCheck(ok=False, steps=[CheckStep(name="Sign in with Microsoft Entra", ok=False,
                                                              detail="Microsoft did not return a token.")])
        try:
            self._company()
            steps.append(CheckStep(name="Company", ok=True, detail="Business Central company found."))
            vendors = self._list("vendors")
            steps.append(CheckStep(name="Read vendors", ok=True, detail=f"{len(vendors)} vendors visible."))
        except ErpError as exc:
            steps.append(CheckStep(name="Company and data", ok=False, detail=str(exc)))
            return ConnectionCheck(ok=False, steps=steps)
        return ConnectionCheck(ok=True, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for v in self._list("vendors"):
            gstin = (v.get("taxRegistrationNumber") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=v["number"], name=v.get("displayName") or v["number"], gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=_dt(v.get("lastModifiedDateTime"))))
        return out

    def _orders(self) -> list[dict[str, Any]]:
        orders = self._list("purchaseOrders", expand="purchaseOrderLines")
        # Orrfin's own drafts stay out of the mirror until a person releases them (status Open).
        return [o for o in orders if not (str(o.get("vendorOrderNumber") or "").startswith(DRAFT_TAG)
                                          and o.get("status") != "Open")]

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        out = []
        for o in self._orders():
            lines = [ln for ln in o.get("purchaseOrderLines") or [] if ln.get("lineType", "Item") == "Item"]
            ref = str(o.get("vendorOrderNumber") or "")
            out.append(ErpPurchaseOrder(
                erp_ref=o["number"], vendor_ref=o.get("vendorNumber") or "", po_date=_d(o.get("orderDate")),
                schedule_date=_d(o.get("requestedReceiptDate")),
                status="to_bill" if o.get("fullyReceived") else "open", currency=o.get("currencyCode") or "INR",
                net_total=_dec(o.get("totalAmountExcludingTax")), tax_total=_dec(o.get("totalTaxAmount")),
                grand_total=_dec(o.get("totalAmountIncludingTax")),
                orrfin_ref=ref[len(DRAFT_TAG):].lower() if ref.startswith(DRAFT_TAG) else None,
                modified=_dt(o.get("lastModifiedDateTime")), po_number=None if ref.startswith(DRAFT_TAG) else ref or None,
                lines=[ErpPoLine(erp_ref=ln["id"], line_no=int(ln.get("sequence") or i), item_code=ln.get("lineObjectNumber") or "",
                                 description=ln.get("description") or "", hsn=None, uom=ln.get("unitOfMeasureCode"),
                                 qty=_dec(ln.get("quantity")), rate=_dec(ln.get("directUnitCost")),
                                 amount=_dec(ln.get("netAmount")), tax_rate=_dec(ln.get("taxPercent")))
                       for i, ln in enumerate(lines, start=1)]))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        out = []
        for o in self._orders():
            received = [ln for ln in o.get("purchaseOrderLines") or [] if _dec(ln.get("receivedQuantity")) > 0]
            if not received:
                continue
            out.append(ErpReceipt(
                erp_ref=f"{o['number']}-RCPT", vendor_ref=o.get("vendorNumber") or "", posting_date=_d(o.get("orderDate")),
                status="received", modified=_dt(o.get("lastModifiedDateTime")),
                lines=[ErpReceiptLine(erp_ref=f"{ln['id']}-RCPT", item_code=ln.get("lineObjectNumber") or "",
                                      qty_received=_dec(ln.get("receivedQuantity")), po_ref=o["number"],
                                      po_line_ref=ln["id"]) for ln in received]))
        return out

    def create_draft_bill(self, bill: DraftBill) -> Created:
        header = self._post("purchaseInvoices", {
            "vendorNumber": bill.vendor_ref, "vendorInvoiceNumber": bill.supplier_invoice_no[:35],
            "invoiceDate": bill.invoice_date.isoformat(), "postingDate": bill.invoice_date.isoformat()})
        try:
            for line in bill.lines:
                self._post(f"purchaseInvoices({header['id']})/purchaseInvoiceLines", {
                    "lineType": "Item", "lineObjectNumber": line.item_code, "description": line.description[:100],
                    "quantity": _num(line.qty), "directUnitCost": _num(line.rate)})
        except ErpRejected:
            # Never leave half a draft behind: a later lookup would "find" an incomplete bill.
            try:
                self._call("DELETE", f"/companies({self._company()})/purchaseInvoices({header['id']})")
            except ErpError:
                pass
            raise
        return Created(erp_doc_name=header.get("number") or header["id"])

    def _complete_or_remove(self, entity: str, rows: list[dict[str, Any]]) -> str | None:
        """A draft is header + lines, written in several calls. A header left without lines (the reply was lost
        between calls) is unfinished: delete it and report "not found", so the retry writes the whole draft."""
        for row in rows:
            if row.get(f"{entity[:-1]}Lines"):
                return row.get("number") or row["id"]
            self._call("DELETE", f"/companies({self._company()})/{entity}({row['id']})")
        return None

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._list("purchaseInvoices", f"vendorNumber eq {odata_quote(vendor_ref)} and "
                                              f"vendorInvoiceNumber eq {odata_quote(supplier_invoice_no[:35])}",
                          expand="purchaseInvoiceLines")
        return self._complete_or_remove("purchaseInvoices", rows)

    def create_draft_po(self, po: DraftPo) -> Created:
        header = self._post("purchaseOrders", {
            "vendorNumber": po.vendor_ref, "orderDate": po.po_date.isoformat(),
            "requestedReceiptDate": po.schedule_date.isoformat(),
            "vendorOrderNumber": f"{DRAFT_TAG}{po.idempotency_key[:KEY_PREFIX].upper()}"})
        try:
            for line in po.lines:
                self._post(f"purchaseOrders({header['id']})/purchaseOrderLines", {
                    "lineType": "Item", "lineObjectNumber": line.item_code, "description": line.description[:100],
                    "quantity": _num(line.qty), "directUnitCost": _num(line.rate)})
        except ErpRejected:
            try:
                self._call("DELETE", f"/companies({self._company()})/purchaseOrders({header['id']})")
            except ErpError:
                pass
            raise
        return Created(erp_doc_name=header.get("number") or header["id"])

    def find_po(self, orrfin_key: str) -> str | None:
        tag = f"{DRAFT_TAG}{orrfin_key[:KEY_PREFIX].upper()}"
        rows = self._list("purchaseOrders", f"vendorOrderNumber eq {odata_quote(tag)}", expand="purchaseOrderLines")
        return self._complete_or_remove("purchaseOrders", rows)

    def seed_demo_data(self, data: Dataset | None = None) -> SeedReport:
        data = data or dataset()
        created: dict[str, int] = {}
        existing: dict[str, int] = {}

        def tally(kind: str, was_created: bool) -> None:
            bucket = created if was_created else existing
            bucket[kind] = bucket.get(kind, 0) + 1

        lines = {line.item_code: line for po in data.purchase_orders for line in po.lines}
        units = {u.get("code") for u in self._list("unitsOfMeasure")}
        for uom in sorted({line.uom for line in lines.values()}):
            code = uom.upper()[:10]
            if code not in units:
                self._post("unitsOfMeasure", {"code": code, "displayName": uom})
            tally("units", code not in units)
        items = {i.get("number") for i in self._list("items")}
        for code, line in lines.items():
            if code not in items:
                self._post("items", {"number": code, "displayName": line.item_name[:100],
                                     "type": "Service" if code.startswith("SVC-") else "Inventory",
                                     "baseUnitOfMeasureCode": line.uom.upper()[:10]})
            tally("items", code not in items)
        vendors = {v.get("displayName"): v.get("number") for v in self._list("vendors")}
        for vendor in data.vendors:
            if vendor.name not in vendors:
                vendors[vendor.name] = self._post("vendors", {"displayName": vendor.name,
                                                              "taxRegistrationNumber": vendor.gstin})["number"]
                tally("vendors", True)
            else:
                tally("vendors", False)
        orders = {str(o.get("vendorOrderNumber")) for o in self._list("purchaseOrders")}
        for po in data.purchase_orders:
            if po.number in orders:
                tally("purchase orders", False)
                continue
            header = self._post("purchaseOrders", {"vendorNumber": vendors[po.vendor.name],
                                                   "orderDate": po.po_date.isoformat(),
                                                   "requestedReceiptDate": po.schedule_date.isoformat(),
                                                   "vendorOrderNumber": po.number})
            for line in po.lines:
                self._post(f"purchaseOrders({header['id']})/purchaseOrderLines", {
                    "lineType": "Item", "lineObjectNumber": line.item_code, "quantity": _num(line.qty),
                    "directUnitCost": _num(line.rate)})
            tally("purchase orders", True)
        return SeedReport(created=created, existing=existing, notes=[
            "Receive the demo POs in Business Central (Purchase Order → Post → Receive) to try the 3-way match; "
            "the standard API can't post receipts.",
            "GST on the POs comes from Business Central's own tax setup."])
