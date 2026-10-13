"""A simulated Business Central (API v2.0) + Microsoft Entra token endpoint, in-process via httpx.MockTransport
(PROMPTS Step 17; ADR 0006).

Routes the adapter uses: POST /{tenant}/oauth2/v2.0/token on login.microsoftonline.com, and on
api.businesscentral.dynamics.com/v2.0/{tenant}/{env}/api/v2.0: GET /companies, GET|POST
/companies({id})/{entity}, POST|DELETE /companies({id})/{entity}({id})[/{lines}], with $filter and
$expand=purchaseOrderLines. Like BC, it refuses unknown vendors and items (400 BadRequest_NotFound) and
recomputes order and invoice totals when lines are added. `empty=True` is a fresh company (seeder tests).
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_rest import Collections, json_error, json_reply, load, odata_filter
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

COMPANY_ID = "8f2b3c1e-0000-4000-8000-0000000000bc"
COMPANY_NAME = "Orrfin Demo Pvt Ltd"
PATH = re.compile(r"^/companies(?:\((?P<cid>[^)]+)\))?(?:/(?P<entity>\w+)(?:\((?P<id>[^)]+)\))?"
                  r"(?:/(?P<child>\w+))?)?$")
CHILDREN = {"purchaseOrders": "purchaseOrderLines", "purchaseInvoices": "purchaseInvoiceLines"}
CENT = Decimal("0.01")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def render(empty: bool = False) -> dict[str, list[dict[str, Any]]]:
    """The canonical dataset in API v2.0 shapes (BC numbers its own documents, e.g. 106001)."""
    docs: dict[str, list[dict[str, Any]]] = {
        "companies": [{"id": COMPANY_ID, "name": COMPANY_NAME, "displayName": COMPANY_NAME}],
        "vendors": [], "items": [], "unitsOfMeasure": [], "purchaseOrders": [], "purchaseOrderLines": [],
        "purchaseInvoices": [], "purchaseInvoiceLines": []}
    if empty:
        return docs
    data = dataset()
    for v in data.vendors:
        docs["vendors"].append({"id": f"vendor-{v.key}", "number": v.key, "displayName": v.name,
                                "taxRegistrationNumber": v.gstin,
                                "lastModifiedDateTime": v.modified.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    lines = {line.item_code: line for po in data.purchase_orders for line in po.lines}
    for uom in sorted({line.uom for line in lines.values()}):
        docs["unitsOfMeasure"].append({"id": f"uom-{uom}", "code": uom.upper()[:10], "displayName": uom})
    for code, line in lines.items():
        docs["items"].append({"id": f"item-{code}", "number": code, "displayName": line.item_name,
                              "baseUnitOfMeasureCode": line.uom.upper()[:10]})
    for n, po in enumerate(data.purchase_orders, start=1):
        po_id = f"po-{n}"
        docs["purchaseOrders"].append({
            "id": po_id, "number": f"{106000 + n}", "orderDate": po.po_date.isoformat(),
            "requestedReceiptDate": po.schedule_date.isoformat(), "vendorNumber": po.vendor.key,
            "vendorOrderNumber": po.number, "status": "Open", "currencyCode": "INR",
            "fullyReceived": po.status == "to_bill", "totalAmountExcludingTax": po.net_total,
            "totalTaxAmount": po.tax_total, "totalAmountIncludingTax": po.grand_total,
            "lastModifiedDateTime": po.modified.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
        for i, line in enumerate(po.lines):
            docs["purchaseOrderLines"].append({
                "id": f"{po_id}-l{i + 1}", "documentId": po_id, "sequence": 10000 * (i + 1), "lineType": "Item",
                "lineObjectNumber": line.item_code, "description": line.item_name,
                "unitOfMeasureCode": line.uom.upper()[:10], "quantity": line.qty, "directUnitCost": line.rate,
                "netAmount": line.amount, "taxPercent": line.tax_rate, "receivedQuantity": po.received(i)})
    return docs


class FakeBusinessCentral:
    def __init__(self, store: SimStore, *, empty: bool = False, client_secret: str | None = None):
        self.data = Collections(store, lambda: render(empty))
        self.client_secret = client_secret

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return self._token(request)
        path = request.url.path
        marker = "/api/v2.0"
        if marker not in path:
            return json_error(404, "BadRequest_ResourceNotFound", "Unknown resource")
        if self.client_secret and request.headers.get("Authorization", "") != "Bearer sim-bc-token":
            return json_error(401, "Authentication_InvalidCredentials", "The token is missing or invalid")
        m = PATH.match(path.split(marker, 1)[1])
        if not m:
            return json_error(404, "BadRequest_ResourceNotFound", "Unknown resource")
        entity, doc_id, child = m["entity"], m["id"], m["child"]
        if entity is None:
            return json_reply(200, {"value": self.data.all("companies")})
        if m["cid"] != COMPANY_ID:
            return json_error(404, "BadRequest_NotFound", "Company not found")
        if request.method == "GET" and doc_id is None:
            return self._list(entity, request.url.params)
        if request.method == "POST" and doc_id is None:
            return self._create(entity, load(request))
        if request.method == "POST" and child:
            return self._add_line(entity, doc_id, child, load(request))
        if request.method == "DELETE" and doc_id:
            doc = self.data.get(entity, doc_id)
            if doc is None:
                return json_error(404, "BadRequest_NotFound", f"{entity} not found")
            self.data.put(entity, {**doc, "_deleted": True})
            return httpx.Response(204)
        return json_error(405, "BadRequest_MethodNotAllowed", request.method)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        if form.get("scope") != "https://api.businesscentral.dynamics.com/.default":
            return json_reply(400, {"error": "invalid_scope"})
        if self.client_secret and form.get("client_secret") != self.client_secret:
            return json_reply(401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret"})
        return json_reply(200, {"token_type": "Bearer", "expires_in": 3599, "access_token": "sim-bc-token"})

    def _live(self, entity: str) -> list[dict[str, Any]]:
        return [d for d in self.data.all(entity) if not d.get("_deleted")]

    def _list(self, entity: str, params) -> httpx.Response:
        try:
            keep = odata_filter(params.get("$filter"))
        except ValueError as exc:
            return json_error(400, "BadRequest_InvalidFilter", str(exc))
        rows = [dict(d) for d in self._live(entity) if keep(d)]
        if entity in CHILDREN and params.get("$expand") == CHILDREN[entity]:
            lines = self._live(CHILDREN[entity])
            for row in rows:
                row[CHILDREN[entity]] = [ln for ln in lines if ln.get("documentId") == row["id"]]
        return json_reply(200, {"value": rows})

    def _create(self, entity: str, body: dict[str, Any]) -> httpx.Response:
        vendors = {v["number"] for v in self._live("vendors")}
        if entity in ("purchaseInvoices", "purchaseOrders"):
            if body.get("vendorNumber") not in vendors:
                return json_error(400, "BadRequest_NotFound", f"Vendor {body.get('vendorNumber')} does not exist")
            series = 107000 if entity == "purchaseInvoices" else 106100
            body = {**body, "number": str(self.data.next_number(entity, series)), "status": "Draft",
                    "currencyCode": "INR", "fullyReceived": False, "totalAmountExcludingTax": 0, "totalTaxAmount": 0,
                    "totalAmountIncludingTax": 0, "lastModifiedDateTime": _now()}
        elif entity == "vendors":
            body = {**body, "number": body.get("number") or f"V{self.data.next_number('vendors', 100):03d}",
                    "lastModifiedDateTime": _now()}
        elif entity == "items":
            if body.get("baseUnitOfMeasureCode") not in {u["code"] for u in self._live("unitsOfMeasure")}:
                return json_error(400, "BadRequest_NotFound", f"Unit {body.get('baseUnitOfMeasureCode')} does not exist")
        elif entity != "unitsOfMeasure":
            return json_error(400, "BadRequest_MethodNotFound", f"Cannot create {entity}")
        doc = self.data.put(entity, {**body, "id": str(uuid.uuid4())})
        return json_reply(201, doc)

    def _add_line(self, entity: str, doc_id: str, child: str, body: dict[str, Any]) -> httpx.Response:
        header = self.data.get(entity, doc_id)
        if header is None or header.get("_deleted") or CHILDREN.get(entity) != child:
            return json_error(404, "BadRequest_NotFound", f"{entity} {doc_id} not found")
        if body.get("lineObjectNumber") not in {i["number"] for i in self._live("items")}:
            return json_error(400, "BadRequest_NotFound", f"Item {body.get('lineObjectNumber')} does not exist")
        qty, cost = Decimal(str(body.get("quantity", 0))), Decimal(str(body.get("directUnitCost", 0)))
        existing = [ln for ln in self._live(child) if ln.get("documentId") == doc_id]
        line = self.data.put(child, {**body, "id": str(uuid.uuid4()), "documentId": doc_id,
                                     "sequence": 10000 * (len(existing) + 1), "netAmount": (qty * cost).quantize(CENT),
                                     "taxPercent": 0, "receivedQuantity": 0,
                                     "unitOfMeasureCode": body.get("unitOfMeasureCode")})
        net = sum((Decimal(str(ln["netAmount"])) for ln in [*existing, line]), Decimal("0"))
        self.data.put(entity, {**header, "totalAmountExcludingTax": net, "totalAmountIncludingTax": net,
                               "lastModifiedDateTime": _now()})
        return json_reply(201, line)
