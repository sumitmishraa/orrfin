"""Zoho Books (India) adapter, API v3 (BUILD_PLAN §4, §8; PROMPTS Step 20).

Auth: Zoho OAuth on the India data centre. The founder makes a **Self Client** in api-console.zoho.in and
generates a one-time code; Orrfin exchanges it once (`exchange_grant_code`, at Save keys) for a refresh token,
which is stored encrypted. Each run trades the refresh token for a short-lived access token (memory only).
Calls: https://www.zohoapis.in/books/v3/<module>?organization_id=…, header `Authorization: Zoho-oauthtoken …`.

Mapping (checked 13 Oct where marked; the rest unverified):
- vendor         = contacts with contact_type vendor (gst_no = GSTIN);
- purchase order  = purchaseorders (status open / billed / closed; draft and cancelled are not mirrored);
                    reference_number holds the PO number the vendor quotes;
- goods receipt   = each PO line's `quantity_received` (Books purchase receives API: unverified);
- draft PO        = purchaseorders in status **draft** (created as draft; Zoho help);
                    lookup = reference_number "ORF-<key prefix>";
- draft bill      = bills; whether an API-created bill is a draft is **unverified**, and an open bill would
                    break "drafts only" (CLAUDE.md). So live Zoho sends bills only after the founder sets
                    "Draft bills checked" = yes on the Connectors page (simulated Zoho always drafts them).
                    Lookup = vendor_id + bill_number.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.erp_demo.canonical import Dataset, dataset
from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpError,
    ErpNotSupported,
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

ACCOUNTS_HOST = "https://accounts.zoho.in"
API_HOST = "https://www.zohoapis.in"
API_BASE = f"{API_HOST}/books/v3"
DRAFT_TAG = "ORF-"
KEY_PREFIX = 20
SCOPES = "ZohoBooks.contacts.ALL,ZohoBooks.settings.ALL,ZohoBooks.purchaseorders.ALL,ZohoBooks.bills.ALL"


def zoho_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    return f"{body.get('message') or body.get('error') or response.text} (code {body.get('code', '?')})"


def exchange_grant_code(accounts: ErpHttp, client_id: str, client_secret: str, code: str) -> str:
    """One-time code from a Zoho Self Client → long-lived refresh token (called once, at Save keys)."""
    accounts.describe_error = zoho_error
    body = accounts.request("POST", "/oauth/v2/token", params={
        "grant_type": "authorization_code", "client_id": client_id, "client_secret": client_secret,
        "code": code}).json()
    if not body.get("refresh_token"):
        raise ErpRejected(f"Zoho did not return a refresh token ({body.get('error') or 'code already used or expired'}). "
                          "Generate a new code (it lasts a few minutes) and save again.")
    return body["refresh_token"]


def _dt(text: str | None) -> datetime:
    return datetime.fromisoformat((text or "2026-01-01T00:00:00+05:30").replace("Z", "+00:00"))


def _d(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class ZohoBooksAdapter:
    def __init__(self, api: ErpHttp, accounts: ErpHttp, *, client_id: str, client_secret: str, refresh_token: str,
                 organization_id: str, label: Label, bill_drafts_checked: bool):
        self.api = api
        self.accounts = accounts
        for http in (api, accounts):
            http.describe_error = zoho_error
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.organization_id = organization_id
        self.label = label
        self.bill_drafts_checked = bill_drafts_checked
        self._token: str | None = None

    # --- plumbing --------------------------------------------------------------------------------
    def _auth(self) -> None:
        if self._token:
            return
        body = self.accounts.request("POST", "/oauth/v2/token", params={
            "grant_type": "refresh_token", "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token}).json()
        if not body.get("access_token"):
            raise ErpRejected(f"Zoho refused the saved keys ({body.get('error', 'no access token')}). "
                              "Generate a new Self Client code and save the keys again.")
        self._token = body["access_token"]
        self.api.secrets = (*self.api.secrets, self._token)
        self.api.client.headers["Authorization"] = f"Zoho-oauthtoken {self._token}"

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        self._auth()
        body = self.api.request(method, path, params={"organization_id": self.organization_id, **(params or {})},
                                **kwargs).json()
        if body.get("code", 0) != 0:
            raise ErpRejected(f"Zoho Books refused it: {body.get('message')} (code {body.get('code')})")
        return body

    def _all(self, module: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows, page = [], 1
        while True:
            body = self._call("GET", f"/{module}", {**(params or {}), "page": page, "per_page": 200})
            rows += body.get(key, [])
            if not (body.get("page_context") or {}).get("has_more_page"):
                return rows
            page += 1

    # --- port ------------------------------------------------------------------------------------
    def capabilities(self) -> Capabilities:
        bills_ok = self.label == "simulated" or self.bill_drafts_checked
        return Capabilities(label=self.label, draft_bill_means="bill in status Draft",
                            draft_po_means="purchase order in status Draft", can_write_bill=bills_ok,
                            write_note="" if bills_ok else
                            "Draft bills are off until you confirm in Zoho Books that an API bill arrives as Draft "
                            "(Connectors page → 'Draft bills checked' = yes). Draft POs work now.")

    def test_connection(self) -> ConnectionCheck:
        try:
            self._auth()
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(name="Sign in to Zoho", ok=False, detail=str(exc))])
        steps = [CheckStep(name="Sign in to Zoho", ok=True, detail="Access token received (India data centre).")]
        try:
            vendors = self._all("contacts", "contacts", {"contact_type": "vendor"})
            steps.append(CheckStep(name="Read vendors", ok=True, detail=f"{len(vendors)} vendors in this organisation."))
        except ErpError as exc:
            steps.append(CheckStep(name="Read vendors", ok=False, detail=f"{exc} Check the organisation ID."))
            return ConnectionCheck(ok=False, steps=steps)
        bills_on = self.bill_drafts_checked or self.label == "simulated"
        steps.append(CheckStep(name="Draft bills", ok=bills_on, detail="On." if bills_on else
                               "Off until checked (draft POs work). See docs/CONNECT_ERPS.md, Zoho section."))
        return ConnectionCheck(ok=True, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for c in self._all("contacts", "contacts", {"contact_type": "vendor"}):
            gstin = (c.get("gst_no") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=str(c["contact_id"]), name=c.get("contact_name") or "", gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=_dt(c.get("last_modified_time"))))
        return out

    def _orders(self) -> list[dict[str, Any]]:
        out = []
        for row in self._all("purchaseorders", "purchaseorders"):
            if row.get("status") in ("draft", "cancelled"):
                continue
            out.append(self._call("GET", f"/purchaseorders/{row['purchaseorder_id']}")["purchaseorder"])
        return out

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        out = []
        for po in self._orders():
            items = po.get("line_items") or []
            lines = [ErpPoLine(
                erp_ref=str(it["line_item_id"]), line_no=i, item_code=it.get("sku") or it.get("name") or "",
                description=it.get("description") or it.get("name") or "", hsn=it.get("hsn_or_sac"),
                uom=it.get("unit"), qty=_dec(it.get("quantity")), rate=_dec(it.get("rate")),
                amount=_dec(it.get("item_total")), tax_rate=_dec(it.get("tax_percentage")))
                for i, it in enumerate(items, start=1)]
            received_all = bool(items) and all(_dec(it.get("quantity_received")) >= _dec(it.get("quantity")) for it in items)
            ref = str(po.get("reference_number") or "")
            status = "closed" if po.get("status") == "closed" else ("to_bill" if received_all else "open")
            out.append(ErpPurchaseOrder(
                erp_ref=po["purchaseorder_number"], vendor_ref=str(po.get("vendor_id") or ""), po_date=_d(po.get("date")),
                schedule_date=_d(po.get("delivery_date")), status=status, currency=po.get("currency_code") or "INR",
                net_total=_dec(po.get("sub_total")), tax_total=_dec(po.get("tax_total")), grand_total=_dec(po.get("total")),
                orrfin_ref=ref[len(DRAFT_TAG):].lower() if ref.startswith(DRAFT_TAG) else None,
                modified=_dt(po.get("last_modified_time")), lines=lines,
                po_number=None if ref.startswith(DRAFT_TAG) else ref or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        out = []
        for po in self._orders():
            received = [it for it in po.get("line_items") or [] if _dec(it.get("quantity_received")) > 0]
            if received:
                out.append(ErpReceipt(
                    erp_ref=f"{po['purchaseorder_number']}-RCV", vendor_ref=str(po.get("vendor_id") or ""),
                    posting_date=_d(po.get("date")), status="received", modified=_dt(po.get("last_modified_time")),
                    lines=[ErpReceiptLine(erp_ref=f"{it['line_item_id']}-RCV", item_code=it.get("sku") or it.get("name") or "",
                                          qty_received=_dec(it.get("quantity_received")),
                                          po_ref=po["purchaseorder_number"], po_line_ref=str(it["line_item_id"]))
                           for it in received]))
        return out

    def _item_ids(self) -> dict[str, str]:
        return {(i.get("sku") or i.get("name")): str(i["item_id"]) for i in self._all("items", "items")}

    def create_draft_bill(self, bill: DraftBill) -> Created:
        if not self.capabilities().can_write_bill:
            raise ErpNotSupported(self.capabilities().write_note)
        items = self._item_ids()
        body = self._call("POST", "/bills", json={
            "vendor_id": bill.vendor_ref, "bill_number": bill.supplier_invoice_no, "date": bill.invoice_date.isoformat(),
            "notes": f"orrfin:{bill.idempotency_key}",
            "line_items": [{"item_id": items.get(line.item_code), "name": line.item_code, "description": line.description,
                            "quantity": _num(line.qty), "rate": _num(line.rate)} for line in bill.lines]})
        return Created(erp_doc_name=body["bill"].get("bill_number") or str(body["bill"]["bill_id"]))

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._all("bills", "bills", {"vendor_id": vendor_ref, "bill_number": supplier_invoice_no})
        rows = [r for r in rows if r.get("bill_number") == supplier_invoice_no and str(r.get("vendor_id")) == vendor_ref]
        return rows[0].get("bill_number") if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        items = self._item_ids()
        body = self._call("POST", "/purchaseorders", json={
            "vendor_id": po.vendor_ref, "date": po.po_date.isoformat(), "delivery_date": po.schedule_date.isoformat(),
            "reference_number": f"{DRAFT_TAG}{po.idempotency_key[:KEY_PREFIX].upper()}",
            "notes": f"Draft from Orrfin for {po.request_number}",
            "line_items": [{"item_id": items.get(line.item_code), "name": line.item_code, "description": line.description,
                            "quantity": _num(line.qty), "rate": _num(line.rate)} for line in po.lines]})
        return Created(erp_doc_name=body["purchaseorder"]["purchaseorder_number"])

    def find_po(self, orrfin_key: str) -> str | None:
        tag = f"{DRAFT_TAG}{orrfin_key[:KEY_PREFIX].upper()}"
        rows = [r for r in self._all("purchaseorders", "purchaseorders", {"reference_number": tag})
                if r.get("reference_number") == tag]
        return rows[0]["purchaseorder_number"] if rows else None

    def seed_demo_data(self, data: Dataset | None = None) -> SeedReport:
        data = data or dataset()
        created: dict[str, int] = {}
        existing: dict[str, int] = {}

        def tally(kind: str, was_created: bool) -> None:
            bucket = created if was_created else existing
            bucket[kind] = bucket.get(kind, 0) + 1

        vendors = {c["contact_name"]: str(c["contact_id"])
                   for c in self._all("contacts", "contacts", {"contact_type": "vendor"})}
        for v in data.vendors:
            found = v.name in vendors
            if not found:
                vendors[v.name] = str(self._call("POST", "/contacts", json={
                    "contact_name": v.name, "company_name": v.name, "contact_type": "vendor",
                    "gst_no": v.gstin, "gst_treatment": "business_gst"})["contact"]["contact_id"])
            tally("vendors", not found)
        items = self._item_ids()
        for line in {l.item_code: l for po in data.purchase_orders for l in po.lines}.values():
            found = line.item_code in items
            if not found:
                items[line.item_code] = str(self._call("POST", "/items", json={
                    "name": line.item_name[:100], "sku": line.item_code, "rate": _num(line.rate),
                    "purchase_rate": _num(line.rate), "item_type": "purchases", "hsn_or_sac": line.hsn,
                    "product_type": "service" if line.item_code.startswith("SVC-") else "goods"})["item"]["item_id"])
            tally("items", not found)
        orders = {r.get("reference_number") for r in self._all("purchaseorders", "purchaseorders")}
        for po in data.purchase_orders:
            if po.number in orders:
                tally("purchase orders", False)
                continue
            body = self._call("POST", "/purchaseorders", json={
                "vendor_id": vendors[po.vendor.name], "date": po.po_date.isoformat(),
                "delivery_date": po.schedule_date.isoformat(), "reference_number": po.number,
                "line_items": [{"item_id": items[l.item_code], "quantity": _num(l.qty), "rate": _num(l.rate)}
                               for l in po.lines]})
            self._call("POST", f"/purchaseorders/{body['purchaseorder']['purchaseorder_id']}/status/open")
            tally("purchase orders", True)
        return SeedReport(created=created, existing=existing, notes=[
            "Receive the demo POs in Zoho Books (Purchase Order → Receive) to try the 3-way match.",
            "GST on the POs comes from Zoho Books' own tax setup."])
