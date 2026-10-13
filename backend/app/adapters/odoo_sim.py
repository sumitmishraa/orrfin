"""A simulated Odoo 19 JSON-2 endpoint (POST /json/2/<model>/<method>), in-process via httpx.MockTransport
(PROMPTS Step 20).

Implements what the Odoo adapter calls, the way Odoo behaves: search_read with domains ([field, op, value],
ops = != > < in "not in"), create with one2many commands [0, 0, {...}] and many2many [6, 0, ids], write, and
the purchase workflow — button_confirm (RFQ → purchase order + an incoming receipt for stockable lines),
stock.picking button_validate (done; partial quantities leave a backorder; PO lines' qty_received go up),
button_lock (locked = closed; Odoo 17+ has no 'done' PO state). Many2one fields are returned as [id, "name"]. `empty=True` is a fresh database (seeder
tests); `api_key` makes it demand `Authorization: bearer <key>`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_rest import json_reply, load
from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import dataset

MANY2ONE = {"partner_id": "res.partner", "product_id": "product.product", "order_id": "purchase.order",
            "picking_id": "stock.picking", "purchase_line_id": "purchase.order.line", "purchase_id": "purchase.order"}
CENT = Decimal("0.01")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _err(message: str, status: int = 422) -> httpx.Response:
    return json_reply(status, {"name": "odoo.exceptions.ValidationError", "message": message, "arguments": [message]})


def _ids(commands: list) -> list[int]:
    """Many2many value: [[6, 0, ids]] commands or a plain list of ids."""
    out: list[int] = []
    for item in commands or []:
        if isinstance(item, list) and item and item[0] == 6:
            out += [int(i) for i in item[2]]
        elif isinstance(item, int):
            out.append(item)
    return out


def _match(record: dict[str, Any], domain: list) -> bool:
    for field, op, value in domain:
        have = record.get(field)
        if op == "=" and not (have == value or (value is False and not have)):
            return False
        if op == "!=" and (have == value or (value is False and not have)):
            return False
        if op in (">", "<"):
            if have in (None, False):
                return False
            diff = Decimal(str(have)) - Decimal(str(value))
            if (op == ">" and diff <= 0) or (op == "<" and diff >= 0):
                return False
        if op == "in" and have not in value:
            return False
        if op == "not in" and have in value:
            return False
    return True


class FakeOdoo:
    def __init__(self, store: SimStore, *, empty: bool = False, api_key: str | None = None):
        self.store = store
        self.empty = empty
        self.api_key = api_key

    # --- state -----------------------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        state = self.store.load()
        if "models" not in state:
            state = {"models": {}, "counters": {}}
            self._seed(state)
        return state

    def _new(self, state: dict[str, Any], model: str, vals: dict[str, Any]) -> int:
        new_id = state["counters"].get(model, 0) + 1
        state["counters"][model] = new_id
        state["models"].setdefault(model, {})[str(new_id)] = {**vals, "id": new_id, "write_date": _now()}
        return new_id

    def _rows(self, state: dict[str, Any], model: str) -> list[dict[str, Any]]:
        return list(state["models"].get(model, {}).values())

    def _get(self, state: dict[str, Any], model: str, rid: int) -> dict[str, Any] | None:
        return state["models"].get(model, {}).get(str(rid))

    def _seed(self, state: dict[str, Any]) -> None:
        for app in ("purchase", "stock", "account"):
            self._new(state, "ir.module.module", {"name": app, "state": "installed"})
        if self.empty:
            return
        data = dataset()
        tax = self._new(state, "account.tax", {"name": "GST 18%", "amount": 18, "amount_type": "percent",
                                               "type_tax_use": "purchase"})
        partners = {v.key: self._new(state, "res.partner", {"name": v.name, "vat": v.gstin, "is_company": True,
                                                             "supplier_rank": 1}) for v in data.vendors}
        products = {}
        for line in {l.item_code: l for po in data.purchase_orders for l in po.lines}.values():
            products[line.item_code] = self._new(state, "product.product", {
                "name": line.item_name, "default_code": line.item_code,
                "type": "service" if line.item_code.startswith("SVC-") else "consu", "uom_name": line.uom})
        for po in data.purchase_orders:
            po_id = self._create_po(state, {"partner_id": partners[po.vendor.key], "partner_ref": po.number,
                                            "date_order": f"{po.po_date} 16:30:00",
                                            "date_planned": f"{po.schedule_date} 10:00:00",
                                            "order_line": [[0, 0, {"product_id": products[l.item_code],
                                                                   "product_qty": str(l.qty), "price_unit": str(l.rate),
                                                                   "name": l.item_name, "tax_ids": [tax]}]
                                                           for l in po.lines]})
            self._confirm(state, po_id)
            lines = sorted((l for l in self._rows(state, "purchase.order.line") if l["order_id"] == po_id),
                           key=lambda l: l["id"])
            for receipt in po.receipts:
                goods = {}
                for i, qty in receipt.quantities.items():
                    if po.lines[i].item_code.startswith("SVC-"):
                        lines[i]["qty_received"] = str(qty)
                    else:
                        goods[products[po.lines[i].item_code]] = qty
                if goods:
                    picking = next(p for p in self._rows(state, "stock.picking")
                                   if p["purchase_id"] == po_id and p["state"] not in ("done", "cancel"))
                    for move in (m for m in self._rows(state, "stock.move") if m["picking_id"] == picking["id"]):
                        move["quantity"] = str(goods.get(move["product_id"], Decimal("0")))
                    self._validate(state, picking["id"], backorder=True, date_done=f"{receipt.posting_date} 18:05:00")
            if po.closed:
                self._get(state, "purchase.order", po_id)["locked"] = True

    # --- workflow ----------------------------------------------------------------------------------------
    def _create_po(self, state, vals: dict[str, Any]) -> int:
        lines = vals.pop("order_line", [])
        po_id = self._new(state, "purchase.order", {**vals, "state": "draft", "locked": False, "origin": vals.get("origin") or False,
                                                    "partner_ref": vals.get("partner_ref") or False})
        self._get(state, "purchase.order", po_id)["name"] = f"P{po_id:05d}"
        for command in lines:
            line = dict(command[2])
            product = self._get(state, "product.product", line["product_id"])
            qty, price = Decimal(str(line["product_qty"])), Decimal(str(line["price_unit"]))
            self._new(state, "purchase.order.line", {
                **line, "order_id": po_id, "product_type": product["type"], "tax_ids": _ids(line.get("tax_ids")),
                "price_subtotal": str((qty * price).quantize(CENT)), "qty_received": "0",
                "product_uom_id": product.get("uom_name") or "Units"})
        self._totals(state, po_id)
        return po_id

    def _totals(self, state, po_id: int) -> None:
        po = self._get(state, "purchase.order", po_id)
        untaxed, tax = Decimal("0"), Decimal("0")
        for line in (l for l in self._rows(state, "purchase.order.line") if l["order_id"] == po_id):
            subtotal = Decimal(line["price_subtotal"])
            untaxed += subtotal
            for tax_id in line.get("tax_ids") or []:
                tax += (subtotal * Decimal(str(self._get(state, "account.tax", tax_id)["amount"])) / 100).quantize(CENT)
        po.update({"amount_untaxed": str(untaxed), "amount_tax": str(tax), "amount_total": str(untaxed + tax)})

    def _confirm(self, state, po_id: int) -> None:
        po = self._get(state, "purchase.order", po_id)
        po.update({"state": "purchase", "write_date": _now()})
        goods = [l for l in self._rows(state, "purchase.order.line")
                 if l["order_id"] == po_id and l["product_type"] != "service"]
        if goods:
            pick = self._new(state, "stock.picking", {"picking_type_code": "incoming", "state": "assigned",
                                                      "purchase_id": po_id, "origin": po["name"],
                                                      "partner_id": po["partner_id"], "date_done": False})
            self._get(state, "stock.picking", pick)["name"] = f"WH/IN/{pick:05d}"
            for line in goods:
                self._new(state, "stock.move", {"picking_id": pick, "product_id": line["product_id"],
                                                "product_uom_qty": line["product_qty"], "quantity": "0",
                                                "purchase_line_id": line["id"]})

    def _validate(self, state, picking_id: int, backorder: bool, date_done: str | None = None) -> None:
        picking = self._get(state, "stock.picking", picking_id)
        picking.update({"state": "done", "date_done": date_done or _now(), "write_date": _now()})
        rest = []
        for move in [m for m in self._rows(state, "stock.move") if m["picking_id"] == picking_id]:
            done, wanted = Decimal(str(move["quantity"])), Decimal(str(move["product_uom_qty"]))
            line = self._get(state, "purchase.order.line", move["purchase_line_id"])
            line["qty_received"] = str(Decimal(str(line["qty_received"])) + done)
            if done < wanted:
                rest.append((move, wanted - done))
            move["product_uom_qty"] = str(done)
        if rest and backorder:
            new = self._new(state, "stock.picking", {**{k: v for k, v in picking.items() if k not in ("id", "name")},
                                                     "state": "assigned", "date_done": False})
            self._get(state, "stock.picking", new)["name"] = f"WH/IN/{new:05d}"
            for move, remaining in rest:
                self._new(state, "stock.move", {"picking_id": new, "product_id": move["product_id"],
                                                "product_uom_qty": str(remaining), "quantity": "0",
                                                "purchase_line_id": move["purchase_line_id"]})

    # --- HTTP ----------------------------------------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.api_key and request.headers.get("Authorization", "").lower() != f"bearer {self.api_key}".lower():
            return json_reply(401, {"name": "werkzeug.exceptions.Unauthorized", "message": "Invalid API key"})
        parts = request.url.path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["json", "2"]:
            return _err("Not found", 404)
        model, method = parts[2], parts[3]
        args = load(request)
        state = self._load()
        try:
            result = self._dispatch(state, model, method, args)
        except KeyError as exc:
            return _err(f"Record does not exist or has been deleted: {exc}")
        except ValueError as exc:
            return _err(str(exc))
        self.store.save(state)
        return json_reply(200, result)

    def _dispatch(self, state, model: str, method: str, args: dict[str, Any]) -> Any:
        if method == "search_read":
            rows = [r for r in self._rows(state, model) if _match(r, args.get("domain") or [])]
            return [self._present(state, r, args.get("fields")) for r in sorted(rows, key=lambda r: r["id"])]
        if method == "create":
            return [self._create(state, model, dict(vals)) for vals in args["vals_list"]]
        if method == "write":
            for rid in args["ids"]:
                record = self._get(state, model, rid)
                if record is None:
                    raise KeyError(f"{model}({rid})")
                record.update({**args["vals"], "write_date": _now()})
            return True
        if model == "purchase.order" and method == "button_confirm":
            for rid in args["ids"]:
                self._confirm(state, rid)
            return True
        if model == "purchase.order" and method == "button_lock":
            for rid in args["ids"]:
                self._get(state, model, rid).update({"locked": True, "write_date": _now()})
            return True
        if model == "stock.picking" and method == "button_validate":
            for rid in args["ids"]:
                self._validate(state, rid, backorder=bool((args.get("context") or {}).get("skip_backorder")))
            return True
        raise ValueError(f"The simulated Odoo doesn't implement {model}.{method}")

    def _create(self, state, model: str, vals: dict[str, Any]) -> int:
        if "partner_id" in vals and self._get(state, "res.partner", vals["partner_id"]) is None:
            raise ValueError(f"Vendor {vals['partner_id']} does not exist")
        if model == "purchase.order":
            for command in vals.get("order_line", []):
                if self._get(state, "product.product", command[2]["product_id"]) is None:
                    raise ValueError(f"Product {command[2]['product_id']} does not exist")
            return self._create_po(state, vals)
        if model == "account.move":
            lines = vals.pop("invoice_line_ids", [])
            for command in lines:
                if self._get(state, "product.product", command[2]["product_id"]) is None:
                    raise ValueError(f"Product {command[2]['product_id']} does not exist")
            move = self._new(state, model, {**vals, "state": "draft", "name": "/"})
            for command in lines:
                self._new(state, "account.move.line", {**command[2], "move_id": move})
            return move
        if model == "product.product":
            vals = {**vals, "supplier_taxes_id": _ids(vals.get("supplier_taxes_id"))}
        return self._new(state, model, vals)

    def _present(self, state, record: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
        out = {}
        for field in fields or list(record):
            value = record.get(field, False)
            if field in MANY2ONE and value:
                target = self._get(state, MANY2ONE[field], value) or {}
                value = [value, target.get("name") or str(value)]
            elif field == "product_uom_id" and value:
                value = [1, value]
            out[field] = value
        return out
