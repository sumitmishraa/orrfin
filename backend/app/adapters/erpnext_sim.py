"""A simulated ERPNext (Frappe) REST server, served in-process through httpx.MockTransport
(BUILD_PLAN §4 connector rules; ADR 0004; PROMPTS Steps 12-15).

The ERPNext adapter is plain HTTP client code. In *simulated* mode (and in every test) its calls are
answered here instead of by a real Frappe site, so the simulated connector and the live one share
every line of client code. It implements only what Orrfin uses, the way Frappe does it:

- GET  /api/resource/<DocType>?filters=[[field, op, value]]&fields=[...]&limit_page_length=0
- GET  /api/resource/<DocType>/<name>        (child tables included)
- POST /api/resource/<DocType>               (insert; docstatus 0 = draft)
- PUT  /api/resource/<DocType>/<name>        (update; docstatus 0 → 1 submits)
- GET  /api/method/frappe.auth.get_logged_user
- POST /api/method/erpnext.buying.doctype.purchase_order.purchase_order.update_status

Like ERPNext, it computes line amounts, taxes ("On Net Total" rows) and totals on save, and a
submitted Purchase Receipt updates its PO's received quantities, % received and status.

ERPNext's own safety nets are applied too, so failure tests meet realistic refusals: supplier
invoice number uniqueness (Accounts Settings), the Unique `orrfin_ref` custom field on Purchase
Order (409 DuplicateEntryError) and link validation (417). `empty=True` starts a blank site, which
is how the live seeder ("Prepare demo data") is tested.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from app.adapters.erpnext import load_erpnext_json
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import IST, dataset

BASE_FILES = {"Supplier": "suppliers.json", "Purchase Order": "purchase_orders.json",
              "Purchase Receipt": "purchase_receipts.json"}
CHILD_TABLES = {"items", "taxes"}
SERIES = {"Purchase Invoice": "ACC-PINV-2026-", "Purchase Order": "PUR-ORD-2026-",
          "Purchase Receipt": "MAT-PRE-2026-"}
NAME_FIELD = {"Supplier": "supplier_name", "Item": "item_code", "UOM": "uom_name",
              "Supplier Group": "supplier_group_name"}
SINGLE = "Accounts Settings"
CENT = Decimal("0.01")
DEMO_COMPANY = "Orrfin Demo Co"
DEMO_ABBR = "ODC"


def _d(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def _compute_totals(doc: dict[str, Any]) -> None:
    """What ERPNext's calculate_taxes_and_totals does, for the fields Orrfin reads."""
    net = Decimal("0")
    for item in doc.get("items") or []:
        item["amount"] = (_d(item.get("qty")) * _d(item.get("rate"))).quantize(CENT)
        net += item["amount"]
    taxes = Decimal("0")
    for row in doc.get("taxes") or []:
        if row.get("charge_type") == "On Net Total":
            row["tax_amount"] = (net * _d(row.get("rate")) / 100).quantize(CENT)
        taxes += _d(row.get("tax_amount"))
    doc["net_total"], doc["total_taxes_and_charges"], doc["grand_total"] = net, taxes, net + taxes


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)  # Frappe sends numbers; the adapter parses them back as Decimal
    raise TypeError(type(value).__name__)


def _reply(status: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body, default=_json_default).encode(),
                          headers={"Content-Type": "application/json"})


def _error(status: int, exc_type: str, message: str) -> httpx.Response:
    return _reply(status, {"exc_type": exc_type, "_server_messages": json.dumps([json.dumps({"message": message})])})


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")


def _matches(doc: dict[str, Any], filters: list[list[Any]]) -> bool:
    for flt in filters:
        field, op, value = flt[-3], flt[-2], flt[-1]
        have = doc.get(field)
        if op == "=" and str(have) != str(value):
            return False
        if op == "!=" and str(have) == str(value):
            return False
        if op == "<" and not (have is not None and float(have) < float(value)):
            return False
        if op == "in" and have not in value:
            return False
    return True


class FakeFrappeServer:
    def __init__(self, fixtures_dir: Path | None, store: SimStore, *, empty: bool = False,
                 required_token: str | None = None):
        self.fixtures_dir = fixtures_dir
        self.store = store
        self.empty = empty
        self.required_token = required_token  # tests check the adapter sends `token key:secret`

    # --- state ---------------------------------------------------------------------------------
    def _base(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Documents the simulated site starts with (re-read every call, like the old fixture adapter)."""
        docs: dict[str, dict[str, dict[str, Any]]] = {}
        if self.empty:
            # A fresh site after the setup wizard: one company and its chart of accounts' tax group.
            docs[SINGLE] = {SINGLE: {"name": SINGLE, "check_supplier_invoice_uniqueness": 0}}
            docs["Company"] = {DEMO_COMPANY: {"name": DEMO_COMPANY, "company_name": DEMO_COMPANY, "abbr": DEMO_ABBR}}
            group = f"Duties and Taxes - {DEMO_ABBR}"
            docs["Account"] = {group: {"name": group, "account_name": "Duties and Taxes", "is_group": 1,
                                       "company": DEMO_COMPANY}}
            return docs
        for doctype, filename in BASE_FILES.items():
            payload = load_erpnext_json((self.fixtures_dir / filename).read_text(encoding="utf-8"))
            docs[doctype] = {d["name"]: d for d in payload["data"]}
        data = dataset()
        docs["Item"] = {line.item_code: {"name": line.item_code, "item_code": line.item_code,
                                         "item_name": line.item_name, "stock_uom": line.uom, "disabled": 0}
                        for po in data.purchase_orders for line in po.lines}
        docs["Custom Field"] = {"Purchase Order-orrfin_ref": {
            "name": "Purchase Order-orrfin_ref", "dt": "Purchase Order", "fieldname": "orrfin_ref",
            "fieldtype": "Data", "unique": 1, "read_only": 1}}
        docs[SINGLE] = {SINGLE: {"name": SINGLE, "check_supplier_invoice_uniqueness": 1}}
        return docs

    def _docs(self, state: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
        docs = self._base()
        for doctype, overlay in state.get("docs", {}).items():
            docs.setdefault(doctype, {}).update(overlay)
        return docs

    def _put(self, state: dict[str, Any], doctype: str, doc: dict[str, Any]) -> None:
        state.setdefault("docs", {}).setdefault(doctype, {})[doc["name"]] = doc

    # --- HTTP ----------------------------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.required_token and request.headers.get("Authorization") != f"token {self.required_token}":
            return _error(401, "AuthenticationError", "Invalid API key or secret")
        path = unquote(request.url.path)
        if path == "/api/method/frappe.auth.get_logged_user":
            return _reply(200, {"message": "orrfin-integration@demo.orrfin.ai"})
        if path.endswith("purchase_order.update_status"):
            return self._update_status(json.loads(request.content or b"{}"))
        if not path.startswith("/api/resource/"):
            return _error(404, "DoesNotExistError", f"No route {path}")
        parts = path[len("/api/resource/"):].split("/", 1)
        doctype, name = parts[0], (parts[1] if len(parts) > 1 else None)
        if request.method == "GET" and name is None:
            return self._list(doctype, request.url.params)
        if request.method == "GET":
            return self._get(doctype, name)
        body = json.loads(request.content or b"{}", parse_float=Decimal)
        if request.method == "POST" and name is None:
            return self._insert(doctype, body)
        if request.method == "PUT" and name is not None:
            return self._update(doctype, name, body)
        return _error(405, "MethodNotAllowed", f"{request.method} {path}")

    def _list(self, doctype: str, params) -> httpx.Response:
        docs = self._docs(self.store.load()).get(doctype, {})
        filters = json.loads(params.get("filters", "[]"))
        fields = json.loads(params.get("fields", '["name"]'))
        rows = []
        for doc in docs.values():
            if not _matches(doc, filters):
                continue
            if fields == ["*"]:
                rows.append({k: v for k, v in doc.items() if k not in CHILD_TABLES})
            else:
                rows.append({f: doc.get(f) for f in fields})
        return _reply(200, {"data": rows})

    def _get(self, doctype: str, name: str) -> httpx.Response:
        doc = self._docs(self.store.load()).get(doctype, {}).get(name)
        if doc is None:
            return _error(404, "DoesNotExistError", f"{doctype} {name} not found")
        return _reply(200, {"data": doc})

    def _insert(self, doctype: str, body: dict[str, Any]) -> httpx.Response:
        state = self.store.load()
        docs = self._docs(state)
        problem = self._validate(doctype, body, docs)
        if problem:
            return problem
        doc = dict(body)
        if doctype in SERIES:
            # Like a naming series: the next number not yet used on this site.
            used = set(docs.get(doctype, {}))
            number = state.setdefault("counters", {}).get(doctype, 0)
            while True:
                number += 1
                if f"{SERIES[doctype]}{number:05d}" not in used:
                    break
            state["counters"][doctype] = number
            doc["name"] = f"{SERIES[doctype]}{number:05d}"
        elif doctype in NAME_FIELD:
            doc["name"] = body.get(NAME_FIELD[doctype]) or body.get("name")
        elif doctype == "Custom Field":
            doc["name"] = f"{body['dt']}-{body['fieldname']}"
        elif doctype == "Account":
            doc["name"] = f"{body['account_name']} - {DEMO_ABBR}"
        else:
            doc["name"] = body.get("name") or f"{doctype}-{len(docs.get(doctype, {})) + 1:05d}"
        if doc["name"] in docs.get(doctype, {}):
            return _error(409, "DuplicateEntryError", f"{doctype} {doc['name']} already exists")
        doc.setdefault("docstatus", 0)
        doc["modified"] = _now()
        for n, item in enumerate(doc.get("items") or [], start=1):
            item.setdefault("name", f"{doc['name']}-{n}")
            item.setdefault("idx", n)
        if doctype in SERIES:
            _compute_totals(doc)
        self._put(state, doctype, doc)
        self.store.save(state)
        return _reply(200, {"data": doc})

    def _update(self, doctype: str, name: str, body: dict[str, Any]) -> httpx.Response:
        state = self.store.load()
        doc = self._docs(state).get(doctype, {}).get(name)
        if doc is None:
            return _error(404, "DoesNotExistError", f"{doctype} {name} not found")
        if int(doc.get("docstatus", 0)) == 1 and doctype != SINGLE:
            return _error(417, "UpdateAfterSubmitError", f"Cannot edit submitted {doctype} {name}")
        doc = {**doc, **body, "modified": _now()}
        if doctype in SERIES:
            _compute_totals(doc)
        if doctype == "Purchase Order" and int(doc.get("docstatus", 0)) == 1:
            doc.setdefault("status", "To Receive and Bill")
            doc.setdefault("per_received", 0.0)
        if doctype == "Purchase Receipt" and int(doc.get("docstatus", 0)) == 1:
            doc.setdefault("status", "To Bill")
            self._receive(state, doc)
        self._put(state, doctype, doc)
        self.store.save(state)
        return _reply(200, {"data": doc})

    def _receive(self, state: dict[str, Any], receipt: dict[str, Any]) -> None:
        """A submitted receipt raises received_qty on its PO lines, then % received and status."""
        docs = self._docs(state).get("Purchase Order", {})
        for po_name in {i.get("purchase_order") for i in receipt.get("items") or [] if i.get("purchase_order")}:
            po = json.loads(json.dumps(docs.get(po_name) or {}, default=str))
            if not po:
                continue
            for item in po.get("items") or []:
                got = sum((_d(r.get("qty")) for r in receipt["items"] if r.get("purchase_order_item") == item["name"]),
                          Decimal("0"))
                item["received_qty"] = str(_d(item.get("received_qty")) + got)
            ordered = sum((_d(i.get("qty")) for i in po.get("items") or []), Decimal("0"))
            received = sum((_d(i.get("received_qty")) for i in po.get("items") or []), Decimal("0"))
            po["per_received"] = float(round(100 * received / ordered, 2)) if ordered else 0.0
            if po.get("status") != "Closed":
                po["status"] = "To Bill" if received >= ordered else "To Receive and Bill"
            po["modified"] = _now()
            self._put(state, "Purchase Order", po)

    def _update_status(self, body: dict[str, Any]) -> httpx.Response:
        state = self.store.load()
        doc = self._docs(state).get("Purchase Order", {}).get(body.get("name", ""))
        if doc is None:
            return _error(404, "DoesNotExistError", "Purchase Order not found")
        self._put(state, "Purchase Order", {**doc, "status": body.get("status"), "modified": _now()})
        self.store.save(state)
        return _reply(200, {"message": None})

    def _validate(self, doctype: str, body: dict[str, Any], docs) -> httpx.Response | None:
        if doctype in ("Purchase Invoice", "Purchase Order", "Purchase Receipt"):
            if body.get("supplier") not in docs.get("Supplier", {}):
                return _error(417, "LinkValidationError", f"Could not find Supplier: {body.get('supplier')}")
            if not body.get("items"):
                return _error(417, "MandatoryError", "Items are required")
            for item in body["items"]:
                if item.get("item_code") not in docs.get("Item", {}):
                    return _error(417, "LinkValidationError", f"Could not find Item: {item.get('item_code')}")
        if doctype == "Purchase Invoice":
            if not body.get("bill_no"):
                return _error(417, "MandatoryError", "Supplier Invoice No (bill_no) is required")
            if docs.get(SINGLE, {}).get(SINGLE, {}).get("check_supplier_invoice_uniqueness"):
                for other in docs.get("Purchase Invoice", {}).values():
                    if (other.get("supplier") == body["supplier"] and other.get("bill_no") == body["bill_no"]
                            and int(other.get("docstatus", 0)) < 2):
                        return _error(417, "ValidationError",
                                      f"Supplier Invoice No exists in Purchase Invoice {other['name']}")
        if doctype == "Purchase Order":
            if not body.get("schedule_date"):
                return _error(417, "MandatoryError", "Required By (schedule_date) is required")
            if "Purchase Order-orrfin_ref" in docs.get("Custom Field", {}) and body.get("orrfin_ref"):
                for other in docs.get("Purchase Order", {}).values():
                    if other.get("orrfin_ref") == body["orrfin_ref"]:
                        return _error(409, "DuplicateEntryError", f"Duplicate Orrfin Ref: {other['name']}")
        if doctype == "Item" and body.get("stock_uom") not in docs.get("UOM", {}) and self.empty:
            return _error(417, "LinkValidationError", f"Could not find UOM: {body.get('stock_uom')}")
        if doctype in ("Purchase Order", "Purchase Invoice") and self.empty:
            for row in body.get("taxes") or []:
                if row.get("account_head") not in docs.get("Account", {}):
                    return _error(417, "LinkValidationError", f"Could not find Account: {row.get('account_head')}")
        if doctype == "Account" and body.get("parent_account") not in docs.get("Account", {}):
            return _error(417, "LinkValidationError", f"Could not find Parent Account: {body.get('parent_account')}")
        if doctype == "Supplier" and body.get("supplier_group") not in docs.get("Supplier Group", {}) and self.empty:
            return _error(417, "LinkValidationError", f"Could not find Supplier Group: {body.get('supplier_group')}")
        return None
