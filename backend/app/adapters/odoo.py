"""Odoo 19 adapter, JSON-2 API (BUILD_PLAN §4, §8; docs/ERP_CONNECTORS.md Odoo row; PROMPTS Step 20).

Odoo runs on the founder's laptop in Docker (infra/docker-compose.yml, profile "odoo"). Calls are
POST {url}/json/2/<model>/<method> with named arguments as JSON, headers `Authorization: bearer <API key>` and
`X-Odoo-Database: <db>` (JSON-2 replaces XML-RPC/JSON-RPC, which are deprecated from Odoo 19).
Many2one fields come back as [id, "Display name"]; one2many writes use commands like [0, 0, {values}].
Field names checked live against Odoo 19.0 (13 Oct): purchase.order.line taxes are `tax_ids` (renamed from
`taxes_id` in older versions).

Mapping:
- vendor         = res.partner with supplier_rank > 0 (vat = GSTIN);
- purchase order  = purchase.order in state purchase (RFQs in draft are not mirrored); partner_ref holds
                    the PO number the vendor quotes; locked = closed (Odoo 17+ dropped the 'done' state);
- goods receipt   = incoming stock.picking in state done, lines = stock.move (purchase_line_id links the PO line);
                    service lines are received on the PO line itself (qty_received), as Odoo does for services;
- draft bill      = account.move with move_type in_invoice — Odoo creates it in state **draft**;
                    lookup = partner + ref (supplier invoice no.);
- draft PO        = purchase.order RFQ (state draft) with origin "orrfin:<key>"; lookup = origin.
"Prepare demo data" creates products, a GST 18% purchase tax if missing, vendors, confirmed POs, and validates
the receipts.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.erp_demo.canonical import IST, Dataset, dataset
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

REQUIRED_APPS = ("purchase", "stock", "account")
ORRFIN = "orrfin:"


def odoo_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    return body.get("message") or body.get("name") or response.text


def _ref(value: Any) -> int | None:
    """Many2one as returned by Odoo: [id, name], an id, or False."""
    if isinstance(value, list | tuple):
        return int(value[0]) if value else None
    return int(value) if value else None


def _dt(text: str | bool | None) -> datetime:
    if not text:
        return datetime(2026, 1, 1, tzinfo=IST)
    return datetime.fromisoformat(str(text).replace(" ", "T")).replace(tzinfo=IST)


def _d(text: str | bool | None) -> date | None:
    return date.fromisoformat(str(text)[:10]) if text else None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, False) else 0))


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


class OdooAdapter:
    def __init__(self, http: ErpHttp, *, label: Label):
        self.http = http
        self.http.describe_error = odoo_error
        self.label = label

    def call(self, model: str, method: str, **kwargs: Any) -> Any:
        return self.http.request("POST", f"/json/2/{model}/{method}", json=kwargs).json()

    def _search_read(self, model: str, domain: list, fields: list[str]) -> list[dict[str, Any]]:
        return self.call(model, "search_read", domain=domain, fields=fields)

    def _codes(self, product_ids: set[int | None]) -> dict[int, str]:
        ids = sorted(i for i in product_ids if i)
        if not ids:
            return {}
        return {p["id"]: p.get("default_code") or "" for p in
                self._search_read("product.product", [["id", "in", ids]], ["id", "default_code"])}

    # --- port ------------------------------------------------------------------------------------
    def capabilities(self) -> Capabilities:
        return Capabilities(label=self.label, draft_bill_means="vendor bill in state Draft",
                            draft_po_means="Request for Quotation (draft purchase order)")

    def test_connection(self) -> ConnectionCheck:
        try:
            apps = self._search_read("ir.module.module", [["name", "in", list(REQUIRED_APPS)]], ["name", "state"])
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(
                name="Reach Odoo", ok=False,
                detail=f"{exc} Is Odoo running (scripts\\dev.ps1 -Odoo) and is the API key right?")])
        steps = [CheckStep(name="Reach Odoo", ok=True, detail="Odoo answered the JSON-2 API with this API key.")]
        installed = {a["name"] for a in apps if a.get("state") == "installed"}
        missing = [app for app in REQUIRED_APPS if app not in installed]
        steps.append(CheckStep(name="Purchase, Inventory, Invoicing apps", ok=not missing,
                               detail="Installed." if not missing else
                               f"Missing: {', '.join(missing)}. Run scripts\\odoo_setup.ps1 (or install them in Odoo → Apps)."))
        return ConnectionCheck(ok=not missing, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        out = []
        for p in self._search_read("res.partner", [["supplier_rank", ">", 0]], ["id", "name", "vat", "write_date"]):
            gstin = (p.get("vat") or "").strip().upper() or None
            out.append(ErpVendor(erp_ref=str(p["id"]), name=p.get("name") or "", gstin=gstin,
                                 state_code=gstin[:2] if gstin else None, modified=_dt(p.get("write_date"))))
        return out

    def _order_lines(self, order_ids: list[int]) -> list[dict[str, Any]]:
        if not order_ids:
            return []
        return self._search_read("purchase.order.line", [["order_id", "in", order_ids]],
                                 ["id", "order_id", "product_id", "product_type", "name", "product_qty", "price_unit",
                                  "price_subtotal", "qty_received", "tax_ids", "product_uom_id"])

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        orders = self._search_read("purchase.order", [["state", "=", "purchase"]],
                                   ["id", "name", "partner_id", "partner_ref", "origin", "date_order", "date_planned",
                                    "state", "locked", "amount_untaxed", "amount_tax", "amount_total", "write_date"])
        lines = self._order_lines([o["id"] for o in orders])
        codes = self._codes({_ref(l.get("product_id")) for l in lines})
        tax_ids = sorted({t for l in lines for t in (l.get("tax_ids") or [])})
        rates = {t["id"]: _dec(t.get("amount")) for t in
                 self._search_read("account.tax", [["id", "in", tax_ids]], ["id", "amount"])} if tax_ids else {}
        out = []
        for o in orders:
            raw = sorted((l for l in lines if _ref(l["order_id"]) == o["id"]), key=lambda l: l["id"])
            po_lines = [ErpPoLine(
                erp_ref=str(l["id"]), line_no=i, item_code=codes.get(_ref(l.get("product_id")), ""),
                description=l.get("name") or "", hsn=None,
                uom=l["product_uom_id"][1] if isinstance(l.get("product_uom_id"), list) else None,
                qty=_dec(l.get("product_qty")), rate=_dec(l.get("price_unit")), amount=_dec(l.get("price_subtotal")),
                tax_rate=sum((rates.get(t, Decimal("0")) for t in l.get("tax_ids") or []), Decimal("0")))
                for i, l in enumerate(raw, start=1)]
            received_all = bool(raw) and all(_dec(l.get("qty_received")) >= _dec(l.get("product_qty")) for l in raw)
            origin = o.get("origin") or ""
            status = "closed" if o.get("locked") else ("to_bill" if received_all else "open")
            out.append(ErpPurchaseOrder(
                erp_ref=o["name"], vendor_ref=str(_ref(o.get("partner_id")) or ""), po_date=_d(o.get("date_order")),
                schedule_date=_d(o.get("date_planned")), status=status, currency="INR",
                net_total=_dec(o.get("amount_untaxed")), tax_total=_dec(o.get("amount_tax")),
                grand_total=_dec(o.get("amount_total")),
                orrfin_ref=origin[len(ORRFIN):len(ORRFIN) + 64] if origin.startswith(ORRFIN) else None,
                modified=_dt(o.get("write_date")), lines=po_lines, po_number=o.get("partner_ref") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        pickings = self._search_read("stock.picking", [["picking_type_code", "=", "incoming"], ["state", "=", "done"]],
                                     ["id", "name", "partner_id", "date_done", "write_date", "origin"])
        ids = [p["id"] for p in pickings]
        moves = self._search_read("stock.move", [["picking_id", "in", ids]],
                                  ["id", "picking_id", "product_id", "quantity", "purchase_line_id"]) if ids else []
        codes = self._codes({_ref(m.get("product_id")) for m in moves})
        out = []
        for p in pickings:
            mine = [m for m in moves if _ref(m["picking_id"]) == p["id"]]
            out.append(ErpReceipt(
                erp_ref=p["name"], vendor_ref=str(_ref(p.get("partner_id")) or ""), posting_date=_d(p.get("date_done")),
                status="received", modified=_dt(p.get("write_date")),
                lines=[ErpReceiptLine(erp_ref=str(m["id"]), item_code=codes.get(_ref(m.get("product_id")), ""),
                                      qty_received=_dec(m.get("quantity")), po_ref=p.get("origin") or None,
                                      po_line_ref=str(_ref(m.get("purchase_line_id")) or "") or None) for m in mine]))
        # Services are received on the PO line itself (no picking), as Odoo does for services.
        orders = self._search_read("purchase.order", [["state", "=", "purchase"]],
                                   ["id", "name", "partner_id", "write_date"])
        lines = [l for l in self._order_lines([o["id"] for o in orders])
                 if l.get("product_type") == "service" and _dec(l.get("qty_received")) > 0]
        svc_codes = self._codes({_ref(l.get("product_id")) for l in lines})
        for o in orders:
            mine = [l for l in lines if _ref(l["order_id"]) == o["id"]]
            if mine:
                out.append(ErpReceipt(
                    erp_ref=f"{o['name']}/SVC", vendor_ref=str(_ref(o.get("partner_id")) or ""), posting_date=None,
                    status="received", modified=_dt(o.get("write_date")),
                    lines=[ErpReceiptLine(erp_ref=f"svc-{l['id']}", item_code=svc_codes.get(_ref(l.get("product_id")), ""),
                                          qty_received=_dec(l.get("qty_received")), po_ref=o["name"],
                                          po_line_ref=str(l["id"])) for l in mine]))
        return out

    def _product_ids(self, codes: list[str]) -> dict[str, int]:
        rows = self._search_read("product.product", [["default_code", "in", codes]], ["id", "default_code"])
        return {r["default_code"]: r["id"] for r in rows}

    def _require_products(self, codes: list[str]) -> dict[str, int]:
        products = self._product_ids(codes)
        missing = [c for c in codes if c not in products]
        if missing:
            raise ErpRejected(f"Odoo has no product with internal reference {', '.join(missing)}.")
        return products

    def create_draft_bill(self, bill: DraftBill) -> Created:
        products = self._require_products([line.item_code for line in bill.lines])
        ids = self.call("account.move", "create", vals_list=[{
            "move_type": "in_invoice", "partner_id": int(bill.vendor_ref), "ref": bill.supplier_invoice_no,
            "invoice_date": bill.invoice_date.isoformat(), "narration": f"{ORRFIN}{bill.idempotency_key}",
            "invoice_line_ids": [[0, 0, {"product_id": products[line.item_code], "quantity": _num(line.qty),
                                         "price_unit": _num(line.rate), "name": line.description,
                                         **({"purchase_line_id": int(line.po_line_ref)}
                                            if (line.po_line_ref or "").isdigit() else {})}]
                                 for line in bill.lines]}])
        return Created(erp_doc_name=f"Draft bill {ids[0]}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        if not vendor_ref.isdigit():
            return None
        rows = self._search_read("account.move", [["move_type", "=", "in_invoice"], ["partner_id", "=", int(vendor_ref)],
                                                  ["ref", "=", supplier_invoice_no], ["state", "!=", "cancel"]], ["id"])
        return f"Draft bill {rows[0]['id']}" if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        products = self._require_products([line.item_code for line in po.lines])
        ids = self.call("purchase.order", "create", vals_list=[{
            "partner_id": int(po.vendor_ref), "origin": f"{ORRFIN}{po.idempotency_key}",
            "date_planned": f"{po.schedule_date.isoformat()} 10:00:00",
            "order_line": [[0, 0, {"product_id": products[line.item_code], "product_qty": _num(line.qty),
                                   "price_unit": _num(line.rate), "name": line.description}] for line in po.lines]}])
        return Created(erp_doc_name=self._search_read("purchase.order", [["id", "=", ids[0]]], ["name"])[0]["name"])

    def find_po(self, orrfin_key: str) -> str | None:
        rows = self._search_read("purchase.order", [["origin", "=", f"{ORRFIN}{orrfin_key}"]], ["name"])
        return rows[0]["name"] if rows else None

    # --- "Prepare demo data" ---------------------------------------------------------------------------
    def seed_demo_data(self, data: Dataset | None = None) -> SeedReport:
        data = data or dataset()
        created: dict[str, int] = {}
        existing: dict[str, int] = {}

        def tally(kind: str, was_created: bool) -> None:
            bucket = created if was_created else existing
            bucket[kind] = bucket.get(kind, 0) + 1

        taxes = self._search_read("account.tax", [["type_tax_use", "=", "purchase"], ["amount", "=", 18],
                                                  ["amount_type", "=", "percent"]], ["id"])
        if taxes:
            tax_id = taxes[0]["id"]
        else:
            tax_id = self.call("account.tax", "create", vals_list=[{
                "name": "GST 18% (Orrfin demo)", "amount": 18, "amount_type": "percent", "type_tax_use": "purchase"}])[0]
            tally("taxes", True)
        lines = {l.item_code: l for po in data.purchase_orders for l in po.lines}
        products = self._product_ids(list(lines))
        for code, line in lines.items():
            found = code in products
            if not found:
                service = code.startswith("SVC-")
                products[code] = self.call("product.product", "create", vals_list=[{
                    "name": line.item_name, "default_code": code, "type": "service" if service else "consu",
                    "is_storable": not service, "purchase_ok": True, "standard_price": _num(line.rate),
                    "supplier_taxes_id": [[6, 0, [tax_id]]]}])[0]
            tally("products", not found)
        partners = {p["name"]: p["id"] for p in self._search_read("res.partner", [["supplier_rank", ">", 0]],
                                                                  ["id", "name"])}
        for v in data.vendors:
            found = v.name in partners
            if not found:
                partners[v.name] = self.call("res.partner", "create", vals_list=[{
                    "name": v.name, "vat": v.gstin, "is_company": True, "supplier_rank": 1}])[0]
            tally("vendors", not found)
        done_refs = {o["partner_ref"] for o in self._search_read("purchase.order", [["partner_ref", "!=", False]],
                                                                 ["partner_ref"])}
        for po in data.purchase_orders:
            if po.number in done_refs:
                tally("purchase orders", False)
                continue
            po_id = self.call("purchase.order", "create", vals_list=[{
                "partner_id": partners[po.vendor.name], "partner_ref": po.number,
                "date_order": f"{po.po_date.isoformat()} 16:30:00",
                "date_planned": f"{po.schedule_date.isoformat()} 10:00:00",
                "order_line": [[0, 0, {"product_id": products[l.item_code], "product_qty": _num(l.qty),
                                       "price_unit": _num(l.rate), "name": l.item_name,
                                       "tax_ids": [[6, 0, [tax_id]]]}] for l in po.lines]}])[0]
            self.call("purchase.order", "button_confirm", ids=[po_id])
            self._receive(po_id, po, products)
            if po.closed:
                self.call("purchase.order", "button_lock", ids=[po_id])
            tally("purchase orders", True)
        return SeedReport(created=created, existing=existing,
                          notes=["Receipts validated in Odoo (Inventory → Receipts); services received on the PO."])

    def _receive(self, po_id: int, po, products: dict[str, int]) -> None:
        po_lines = {_ref(l["product_id"]): l for l in self._order_lines([po_id])}
        for receipt in po.receipts:
            goods = {}
            for i, qty in receipt.quantities.items():
                code = po.lines[i].item_code
                if code.startswith("SVC-"):
                    line = po_lines[products[code]]
                    self.call("purchase.order.line", "write", ids=[line["id"]], vals={"qty_received": _num(qty)})
                else:
                    goods[products[code]] = qty
            if not goods:
                continue
            picking = self._search_read("stock.picking", [["purchase_id", "=", po_id],
                                                          ["state", "not in", ["done", "cancel"]]], ["id"])
            if not picking:
                raise ErpRejected(f"Odoo created no receipt for {po.number}; is the Inventory app installed?")
            for move in self._search_read("stock.move", [["picking_id", "=", picking[0]["id"]]], ["id", "product_id"]):
                self.call("stock.move", "write", ids=[move["id"]],
                          vals={"quantity": _num(goods.get(_ref(move["product_id"]), Decimal("0")))})
            # A partial receipt leaves a backorder for the rest, as a warehouse person would.
            self.call("stock.picking", "button_validate", ids=[picking[0]["id"]], context={"skip_backorder": True})
