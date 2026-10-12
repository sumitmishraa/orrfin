"""ERPNext adapter over Frappe's REST API (BUILD_PLAN §2, §4, §8; PROMPTS Steps 12-15).

One class for both modes. *Live*: `token <api_key>:<api_secret>` against the founder's Frappe site.
*Simulated* (and tests): the same calls answered by `erpnext_sim.FakeFrappeServer`. Field names stay
inside app/adapters/; documents are translated by `erpnext.py`.

§8 for ERPNext:
- draft bill  = Purchase Invoice with docstatus 0; lookup = supplier + bill_no (ERPNext's "Check Supplier
  Invoice Number Uniqueness" is the second net); remarks carry `orrfin:<idempotency key>`.
- draft PO    = Purchase Order with docstatus 0; lookup = the Unique custom field `orrfin_ref`.
"Prepare demo data" creates that custom field (and "Orrfin PO No", which holds the canonical PO number the
demo invoices quote), turns the uniqueness check on and adds Input GST accounts, so the founder doesn't
have to click through Customize Form. Documents are submitted with Frappe's documented
`frappe.client.submit` method.
"""

import json
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.erpnext import (
    is_submitted,
    load_erpnext_json,
    purchase_order_to_record,
    purchase_receipt_to_record,
    supplier_to_vendor,
)
from app.erp_demo.canonical import Dataset, dataset
from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpError,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpRejected,
    ErpVendor,
    Label,
    SeedReport,
)
from app.security.outbound import ErpHttp

CUSTOM_FIELDS = {  # fieldname → (label, unique); ERPNext v15's UI may prefix "custom_", so both spellings count
    "orrfin_ref": ("Orrfin Ref", 1),
    "orrfin_po_number": ("Orrfin PO No", 0),
}
ACCOUNTS_SETTINGS = "Accounts Settings"
GST_HEADS = ("CGST", "SGST", "IGST")


def frappe_error(response: httpx.Response) -> str:
    """Frappe puts the human message in `_server_messages` (a JSON list of JSON objects)."""
    body = response.json()
    messages = []
    for raw in json.loads(body.get("_server_messages") or "[]"):
        try:
            messages.append(json.loads(raw).get("message", ""))
        except (ValueError, AttributeError):
            messages.append(str(raw))
    text = "; ".join(m for m in messages if m) or body.get("exception") or body.get("exc_type") or response.text
    return f"{body.get('exc_type', '')}: {text}".strip(": ")


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class ErpnextAdapter:
    def __init__(self, http: ErpHttp, *, label: Label, company: str | None = None):
        self.http = http
        self.http.describe_error = frappe_error
        self.label = label
        self.company = company or None
        self._po_fields: dict[str, str] | None = None

    # --- plumbing ------------------------------------------------------------------------------
    def _json(self, response: httpx.Response) -> Any:
        return load_erpnext_json(response.text)

    def _list(self, doctype: str, filters: list | None = None, fields: list[str] | None = None) -> list[dict]:
        params = {"filters": json.dumps(filters or []), "fields": json.dumps(fields or ["name"]),
                  "limit_page_length": "0"}
        return self._json(self.http.request("GET", f"/api/resource/{doctype}", params=params))["data"]

    def _get(self, doctype: str, name: str) -> dict[str, Any] | None:
        try:
            return self._json(self.http.request("GET", f"/api/resource/{doctype}/{name}"))["data"]
        except ErpRejected as exc:
            if exc.status == 404:
                return None
            raise

    def _insert(self, doctype: str, doc: dict[str, Any]) -> dict[str, Any]:
        return self._json(self.http.request("POST", f"/api/resource/{doctype}", json=doc))["data"]

    def _update(self, doctype: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._json(self.http.request("PUT", f"/api/resource/{doctype}/{name}", json=values))["data"]

    def _po_field(self, fieldname: str = "orrfin_ref") -> str:
        """The spelling this site uses for one of Orrfin's Purchase Order custom fields, or "" if missing."""
        if self._po_fields is None:
            rows = self._list("Custom Field", [["dt", "=", "Purchase Order"]], ["name", "fieldname"])
            names = {r.get("fieldname") for r in rows}
            self._po_fields = {f: next((s for s in (f, f"custom_{f}") if s in names), "") for f in CUSTOM_FIELDS}
        return self._po_fields[fieldname]

    def _submit(self, doctype: str, name: str) -> None:
        """Submit a saved document through Frappe's documented whitelisted method."""
        doc = self._get(doctype, name)
        self.http.request("POST", "/api/method/frappe.client.submit", json={"doc": {**doc, "doctype": doctype}})

    # --- port ------------------------------------------------------------------------------------
    def capabilities(self) -> Capabilities:
        return Capabilities(label=self.label,
                            draft_bill_means="Purchase Invoice saved as Draft (not submitted)",
                            draft_po_means="Purchase Order saved as Draft (not submitted)")

    def test_connection(self) -> ConnectionCheck:
        steps: list[CheckStep] = []
        try:
            user = self._json(self.http.request("GET", "/api/method/frappe.auth.get_logged_user"))["message"]
            steps.append(CheckStep(name="Sign in", ok=True, detail=f"Signed in as {user}."))
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(name="Sign in", ok=False, detail=str(exc))])
        try:
            suppliers = self._list("Supplier")
            steps.append(CheckStep(name="Read suppliers", ok=True, detail=f"{len(suppliers)} suppliers visible."))
        except ErpError as exc:
            steps.append(CheckStep(name="Read suppliers", ok=False, detail=str(exc)))
            return ConnectionCheck(ok=False, steps=steps)
        field = self._po_field()
        steps.append(CheckStep(name="Orrfin Ref field on Purchase Order", ok=bool(field),
                               detail="Present (stops duplicate draft POs)." if field
                               else "Missing. Click 'Prepare demo data' and Orrfin creates it."))
        settings = self._get(ACCOUNTS_SETTINGS, ACCOUNTS_SETTINGS) or {}
        unique = bool(int(settings.get("check_supplier_invoice_uniqueness") or 0))
        steps.append(CheckStep(name="Supplier invoice number uniqueness", ok=unique,
                               detail="On (ERPNext's own duplicate-bill check)." if unique
                               else "Off. Click 'Prepare demo data' and Orrfin turns it on."))
        return ConnectionCheck(ok=True, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        # Suppliers are masters (never submitted), so "disabled" is the filter, not docstatus.
        return [supplier_to_vendor(d) for d in self._list("Supplier", fields=["*"]) if not int(d.get("disabled") or 0)]

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        names = [r["name"] for r in self._list("Purchase Order", [["docstatus", "=", 1]])]
        docs = [self._get("Purchase Order", n) for n in names]
        return [purchase_order_to_record(d) for d in docs if d and is_submitted(d)]

    def list_receipts(self) -> list[ErpReceipt]:
        names = [r["name"] for r in self._list("Purchase Receipt", [["docstatus", "=", 1]])]
        docs = [self._get("Purchase Receipt", n) for n in names]
        return [purchase_receipt_to_record(d) for d in docs if d and is_submitted(d)]

    def create_draft_bill(self, bill: DraftBill) -> Created:
        doc = {
            "supplier": bill.vendor_ref, "bill_no": bill.supplier_invoice_no, "bill_date": bill.invoice_date.isoformat(),
            "posting_date": bill.invoice_date.isoformat(), "set_posting_time": 1, "currency": bill.currency,
            "docstatus": 0,  # draft: a person submits it inside ERPNext (§8)
            "remarks": (f"orrfin:{bill.idempotency_key} | Approved in Orrfin. Invoice total {bill.grand_total} "
                        f"(CGST {bill.cgst}, SGST {bill.sgst}, IGST {bill.igst})."),
            "items": [{"item_code": line.item_code, "description": line.description, "qty": _num(line.qty),
                       "rate": _num(line.rate), "purchase_order": bill.po_ref, "po_detail": line.po_line_ref}
                      for line in bill.lines],
        }
        if self.company:
            doc["company"] = self.company
        return Created(erp_doc_name=self._insert("Purchase Invoice", doc)["name"])

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        rows = self._list("Purchase Invoice", [["supplier", "=", vendor_ref], ["bill_no", "=", supplier_invoice_no],
                                               ["docstatus", "<", 2]])
        return rows[0]["name"] if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        field = self._po_field()
        if not field:
            raise ErpRejected("ERPNext has no 'Orrfin Ref' field on Purchase Order, so a duplicate-safe draft "
                              "can't be made. Click 'Prepare demo data' on the Connectors page first.")
        doc = {
            "supplier": po.vendor_ref, "transaction_date": po.po_date.isoformat(),
            "schedule_date": po.schedule_date.isoformat(), "currency": po.currency, "docstatus": 0,
            field: po.idempotency_key,
            "items": [{"item_code": line.item_code, "description": line.description, "qty": _num(line.qty),
                       "rate": _num(line.rate), "schedule_date": po.schedule_date.isoformat()} for line in po.lines],
        }
        if self.company:
            doc["company"] = self.company
        return Created(erp_doc_name=self._insert("Purchase Order", doc)["name"])

    def find_po(self, orrfin_key: str) -> str | None:
        field = self._po_field()
        if not field:
            return None
        rows = self._list("Purchase Order", [[field, "=", orrfin_key]])
        return rows[0]["name"] if rows else None

    # --- "Prepare demo data" -----------------------------------------------------------------------
    def seed_demo_data(self, data: Dataset | None = None) -> SeedReport:
        data = data or dataset()
        created: dict[str, int] = {}
        existing: dict[str, int] = {}
        notes: list[str] = []

        def tally(kind: str, was_created: bool) -> None:
            bucket = created if was_created else existing
            bucket[kind] = bucket.get(kind, 0) + 1

        # Safety nets first (§8 "Before the demo").
        for fieldname, (label, unique) in CUSTOM_FIELDS.items():
            if not self._po_field(fieldname):
                self._insert("Custom Field", {"dt": "Purchase Order", "fieldname": fieldname, "label": label,
                                              "fieldtype": "Data", "unique": unique, "read_only": 1, "no_copy": 1,
                                              "insert_after": "supplier"})
                self._po_fields = None
                tally("custom fields", True)
                notes.append(f"Added the '{label}' field to Purchase Order.")
        settings = self._get(ACCOUNTS_SETTINGS, ACCOUNTS_SETTINGS) or {}
        if not int(settings.get("check_supplier_invoice_uniqueness") or 0):
            self._update(ACCOUNTS_SETTINGS, ACCOUNTS_SETTINGS, {"check_supplier_invoice_uniqueness": 1})
            notes.append("Turned on 'Check Supplier Invoice Number Uniqueness'.")

        tax_accounts = self._gst_accounts(tally, notes)

        for group in sorted({v.group for v in data.vendors}):
            if self._get("Supplier Group", group) is None:
                self._insert("Supplier Group", {"supplier_group_name": group, "parent_supplier_group": "All Supplier Groups"})
                tally("supplier groups", True)
        lines = {line.item_code: line for po in data.purchase_orders for line in po.lines}
        for uom in sorted({line.uom for line in lines.values()}):
            if self._get("UOM", uom) is None:
                self._insert("UOM", {"uom_name": uom})
                tally("units", True)
        for code, line in lines.items():
            found = self._get("Item", code) is not None
            if not found:
                self._insert("Item", {"item_code": code, "item_name": line.item_name, "description": line.item_name,
                                      "item_group": "All Item Groups", "stock_uom": line.uom, "gst_hsn_code": line.hsn,
                                      "is_stock_item": 0 if code.startswith("SVC-") else 1, "is_purchase_item": 1})
            tally("items", not found)
        for vendor in data.vendors:
            found = self._get("Supplier", vendor.name) is not None
            if not found:
                # `gstin` needs the India Compliance app; `tax_id` is core. Frappe ignores unknown fields.
                self._insert("Supplier", {"supplier_name": vendor.name, "supplier_group": vendor.group,
                                          "supplier_type": "Company", "country": "India",
                                          "gstin": vendor.gstin, "tax_id": vendor.gstin})
            tally("suppliers", not found)

        for po in data.purchase_orders:
            number_field = self._po_field("orrfin_po_number")
            rows = self._list("Purchase Order", [[number_field, "=", po.number], ["docstatus", "<", 2]])
            if rows:
                tally("purchase orders", False)
                po_name = rows[0]["name"]
            else:
                # Same-state suppliers: CGST 9% + SGST 9%; others IGST 18% (BUILD_PLAN §6 tax rule).
                heads = (("CGST", 9), ("SGST", 9)) if po.vendor.same_state else (("IGST", 18),)
                doc = {"supplier": po.vendor.name, "transaction_date": po.po_date.isoformat(),
                       "schedule_date": po.schedule_date.isoformat(), number_field: po.number,
                       "items": [{"item_code": l.item_code, "qty": _num(l.qty), "rate": _num(l.rate),
                                  "schedule_date": po.schedule_date.isoformat()} for l in po.lines],
                       "taxes": [{"charge_type": "On Net Total", "account_head": tax_accounts[head], "rate": rate,
                                  "description": head, "category": "Total", "add_deduct_tax": "Add"}
                                 for head, rate in heads]}
                if self.company:
                    doc["company"] = self.company
                po_name = self._insert("Purchase Order", doc)["name"]
                self._submit("Purchase Order", po_name)
                tally("purchase orders", True)
            po_doc = self._get("Purchase Order", po_name) or {}
            item_rows = {i["item_code"]: i["name"] for i in po_doc.get("items", [])}
            for receipt in po.receipts:
                found = self._list("Purchase Receipt", [["supplier_delivery_note", "=", receipt.number],
                                                        ["docstatus", "<", 2]])
                if found:
                    tally("goods receipts", False)
                    continue
                items = [{"item_code": po.lines[i].item_code, "qty": _num(q), "received_qty": _num(q),
                          "rate": _num(po.lines[i].rate), "purchase_order": po_name,
                          "purchase_order_item": item_rows.get(po.lines[i].item_code)}
                         for i, q in receipt.quantities.items()]
                pr = {"supplier": po.vendor.name, "posting_date": receipt.posting_date.isoformat(),
                      "set_posting_time": 1, "supplier_delivery_note": receipt.number, "items": items}
                if self.company:
                    pr["company"] = self.company
                pr_name = self._insert("Purchase Receipt", pr)["name"]
                self._submit("Purchase Receipt", pr_name)
                tally("goods receipts", True)
            if po.closed and po_doc.get("status") != "Closed":
                self.http.request("POST", "/api/method/erpnext.buying.doctype.purchase_order.purchase_order."
                                          "update_status", json={"status": "Closed", "name": po_name})
        return SeedReport(created=created, existing=existing, notes=notes)

    def _gst_accounts(self, tally, notes: list[str]) -> dict[str, str]:
        """Input GST accounts under the company's "Duties and Taxes" group, created if missing."""
        companies = self._list("Company", [["name", "=", self.company]] if self.company else [], ["name", "abbr"])
        if not companies:
            raise ErpRejected("ERPNext has no company yet. Finish ERPNext's setup wizard (it creates the company).")
        company = companies[0]
        accounts: dict[str, str] = {}
        for head in GST_HEADS:
            rows = self._list("Account", [["account_name", "=", f"Input Tax {head}"],
                                          ["company", "=", company["name"]]], ["name"])
            if rows:
                accounts[head] = rows[0]["name"]
                continue
            parents = self._list("Account", [["account_name", "=", "Duties and Taxes"], ["is_group", "=", 1],
                                             ["company", "=", company["name"]]], ["name"])
            if not parents:
                raise ErpRejected("ERPNext's chart of accounts has no 'Duties and Taxes' group for "
                                  f"{company['name']}; add one, then run Prepare demo data again.")
            accounts[head] = self._insert("Account", {
                "account_name": f"Input Tax {head}", "parent_account": parents[0]["name"],
                "company": company["name"], "account_type": "Tax", "is_group": 0})["name"]
            tally("tax accounts", True)
            notes.append(f"Added account {accounts[head]}.")
        return accounts
