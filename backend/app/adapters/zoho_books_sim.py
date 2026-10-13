"""A simulated Zoho Books (India) API v3 + Zoho Accounts token endpoint, in-process via httpx.MockTransport
(PROMPTS Step 20).

accounts.zoho.in/oauth/v2/token: grant_type authorization_code (one-time Self Client code → refresh token)
and refresh_token (→ access token). www.zohoapis.in/books/v3: contacts, items, purchaseorders (+ /status/open),
bills; every call needs organization_id and the Zoho-oauthtoken header, as in Zoho. Replies carry Zoho's
{"code": 0, "message": "success", ...} envelope; refusals use non-zero codes with HTTP 400.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_rest import Collections, json_reply, load
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

ORG_ID = "60012345678"
GRANT_CODE = "1000.simulated-grant-code"
REFRESH = "1000.simulated-refresh-token"
ACCESS = "1000.simulated-access-token"
MODULES = {"contacts": "contact_id", "items": "item_id", "purchaseorders": "purchaseorder_id", "bills": "bill_id"}
SINGULAR = {"contacts": "contact", "items": "item", "purchaseorders": "purchaseorder", "bills": "bill"}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _refuse(code: int, message: str) -> httpx.Response:
    return json_reply(400, {"code": code, "message": message})


def render(empty: bool) -> dict[str, list[dict[str, Any]]]:
    docs: dict[str, list[dict[str, Any]]] = {name: [] for name in MODULES}
    if empty:
        return docs
    data = dataset()
    vendor_id = {}
    for n, v in enumerate(data.vendors, start=1):
        vendor_id[v.key] = f"4600000000000{n}"
        docs["contacts"].append({"contact_id": vendor_id[v.key], "contact_name": v.name, "contact_type": "vendor",
                                 "gst_no": v.gstin, "last_modified_time": v.modified.isoformat()})
    item_id = {}
    for n, line in enumerate({l.item_code: l for po in data.purchase_orders for l in po.lines}.values(), start=1):
        item_id[line.item_code] = f"4610000000000{n:02d}"
        docs["items"].append({"item_id": item_id[line.item_code], "sku": line.item_code, "name": line.item_name,
                              "rate": line.rate})
    for n, po in enumerate(data.purchase_orders, start=1):
        docs["purchaseorders"].append({
            "purchaseorder_id": f"4620000000000{n}", "purchaseorder_number": f"PO-{n:05d}",
            "vendor_id": vendor_id[po.vendor.key], "date": po.po_date.isoformat(),
            "delivery_date": po.schedule_date.isoformat(), "reference_number": po.number,
            "status": {"closed": "closed", "to_bill": "billed", "open": "open"}[po.status], "currency_code": "INR",
            "sub_total": po.net_total, "tax_total": po.tax_total, "total": po.grand_total,
            "last_modified_time": po.modified.isoformat(),
            "line_items": [{"line_item_id": f"4620000000000{n}{i}", "item_id": item_id[line.item_code],
                            "sku": line.item_code, "name": line.item_name, "description": line.item_name,
                            "hsn_or_sac": line.hsn, "unit": line.uom, "quantity": line.qty, "rate": line.rate,
                            "item_total": line.amount, "tax_percentage": line.tax_rate,
                            "quantity_received": po.received(i)} for i, line in enumerate(po.lines)]})
    return docs


class FakeZohoBooks:
    def __init__(self, store: SimStore, *, empty: bool = False, client_secret: str | None = None):
        base = render(empty)
        self.data = {module: Collections(store, lambda m=module: {m: base[m]}, id_field=key)
                     for module, key in MODULES.items()}
        self.client_secret = client_secret

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.zoho.in":
            return self._token(request.url.params)
        if self.client_secret and request.headers.get("Authorization") != f"Zoho-oauthtoken {ACCESS}":
            return json_reply(401, {"code": 57, "message": "You are not authorized to perform this operation"})
        if request.url.params.get("organization_id") != ORG_ID:
            return _refuse(6041, "This user is not associated with this organization.")
        parts = request.url.path.split("/books/v3/", 1)[-1].strip("/").split("/")
        module = parts[0]
        if module not in MODULES:
            return _refuse(5, "Invalid URL Passed")
        if request.method == "GET" and len(parts) == 1:
            filters = {k: v for k, v in request.url.params.items() if k not in ("organization_id", "page", "per_page")}
            rows = [d for d in self.data[module].all(module)
                    if all(str(d.get(k) or "") == v for k, v in filters.items())]
            return json_reply(200, {"code": 0, "message": "success", module: rows,
                                    "page_context": {"page": 1, "has_more_page": False}})
        if request.method == "GET":
            doc = self.data[module].get(module, parts[1])
            return json_reply(200, {"code": 0, "message": "success", SINGULAR[module]: doc}) if doc \
                else _refuse(1002, f"{SINGULAR[module]} does not exist.")
        if request.method == "POST" and len(parts) == 4 and parts[2:] == ["status", "open"]:
            doc = self.data[module].get(module, parts[1])
            if doc is None:
                return _refuse(1002, "Purchase order does not exist.")
            self.data[module].put(module, {**doc, "status": "open", "last_modified_time": _now()})
            return json_reply(200, {"code": 0, "message": "The purchase order has been marked as open."})
        if request.method == "POST" and len(parts) == 1:
            return self._create(module, load(request))
        return _refuse(5, "Invalid URL Passed")

    def _token(self, params) -> httpx.Response:
        if self.client_secret and params.get("client_secret") != self.client_secret:
            return json_reply(200, {"error": "invalid_client"})
        if params.get("grant_type") == "authorization_code":
            if params.get("code") != GRANT_CODE:
                return json_reply(200, {"error": "invalid_code"})
            return json_reply(200, {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600})
        if params.get("grant_type") == "refresh_token" and params.get("refresh_token") == REFRESH:
            return json_reply(200, {"access_token": ACCESS, "expires_in": 3600, "api_domain": "https://www.zohoapis.in"})
        return json_reply(200, {"error": "invalid_code"})

    def _create(self, module: str, body: dict[str, Any]) -> httpx.Response:
        store = self.data[module]
        n = store.next_number(module, 100)
        if module == "contacts":
            doc = {**body, "contact_id": f"47{n:013d}", "last_modified_time": _now()}
        elif module == "items":
            doc = {**body, "item_id": f"48{n:013d}"}
        else:
            if self.data["contacts"].get("contacts", body.get("vendor_id", "")) is None:
                return _refuse(1002, "Vendor does not exist.")
            items = {i["item_id"]: i for i in self.data["items"].all("items")}
            lines = []
            for i, line in enumerate(body.get("line_items") or []):
                item = items.get(line.get("item_id"))
                if item is None:
                    return _refuse(1004, f"Item {line.get('name') or line.get('item_id')} does not exist.")
                qty, rate = Decimal(str(line["quantity"])), Decimal(str(line["rate"]))
                lines.append({**line, "line_item_id": f"49{n:010d}{i}", "sku": item.get("sku"), "name": item.get("name"),
                              "item_total": str(qty * rate), "tax_percentage": "0", "quantity_received": "0"})
            total = sum((Decimal(line["item_total"]) for line in lines), Decimal("0"))
            if module == "bills":
                for other in store.all("bills"):
                    if other["vendor_id"] == body.get("vendor_id") and other["bill_number"] == body.get("bill_number"):
                        return _refuse(13011, "Bill number already exists for this vendor.")
                doc = {**body, "bill_id": f"50{n:013d}", "status": "draft", "line_items": lines, "total": str(total)}
            else:
                doc = {**body, "purchaseorder_id": f"51{n:013d}", "purchaseorder_number": f"PO-{n:05d}",
                       "status": "draft", "line_items": lines, "sub_total": str(total), "tax_total": "0",
                       "total": str(total), "currency_code": "INR", "last_modified_time": _now()}
        store.put(module, doc)
        return json_reply(201, {"code": 0, "message": "created", SINGULAR[module]: doc})
