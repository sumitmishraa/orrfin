"""One adapter for every ERP described in `dialects.py` (BUILD_PLAN §4, §8; PROMPTS Step 36).

The ERP-specific part is only names: which resource holds vendors, which field holds the PO number,
which status means "draft". The rules are the same as every other connector: read vendors, POs and
receipts into Orrfin's shapes with Decimal money; write only *draft* bills and *draft* POs, each
tagged `orrfin:<key>` so a lookup can find it before any retry (§8). No ledger posting, no vendor writes.
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.adapters.dialects import Dialect
from app.erp_demo.canonical import IST
from app.ports.erp import (
    Capabilities, CheckStep, ConnectionCheck, Created, DraftBill, DraftPo, ErpPoLine, ErpPurchaseOrder, ErpReceipt,
    ErpReceiptLine, ErpVendor, SeedReport,
)
from app.security.outbound import ErpHttp

ORRFIN_TAG = re.compile(r"orrfin:([0-9a-f]{64})")
CENT = Decimal("0.01")


def dig(doc: Any, path: str) -> Any:
    for part in path.split(".") if path else []:
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def plant(doc: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value
    return doc


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _stamp(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value or "2026-01-01T00:00:00")[:19])
    return moment.replace(tzinfo=IST)


class DialectAdapter:
    def __init__(self, http: ErpHttp, dialect: Dialect):
        self.http, self.d = http, dialect
        self.contract_gaps = set(dialect.gaps)

    def _list(self, logical: str, **params: str) -> list[dict[str, Any]]:
        resource = self.d.collections[logical]
        reply = self.http.request("GET", f"/{resource}", params=params).json()
        found = dig(reply, self.d.envelope.format(c=resource.split("/")[-1])) if self.d.envelope else reply
        return list(found or [])

    def _post(self, logical: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("POST", f"/{self.d.collections[logical]}", json=body).json()

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated", draft_bill_means=self.d.draft_bill_means, draft_po_means=self.d.draft_po_means)

    def test_connection(self) -> ConnectionCheck:
        vendors = self._list("vendors")
        return ConnectionCheck(ok=True, steps=[CheckStep(name=f"Simulated {self.d.name}", ok=True,
                                                         detail=f"Connected; {len(vendors)} vendors.")])

    def list_vendors(self) -> list[ErpVendor]:
        f, out = self.d.f, []
        for v in self._list("vendors"):
            tax = (str(dig(v, f["vendor_tax"]) or "").strip().upper()) or None
            out.append(ErpVendor(erp_ref=str(dig(v, f["vendor_id"])), name=str(dig(v, f["vendor_name"]) or ""),
                                 gstin=tax, state_code=tax[:2] if tax and tax[:2].isdigit() else None,
                                 modified=_stamp(dig(v, f["modified"]))))
        return out

    def _received(self) -> dict[tuple[str, str], Decimal]:
        f, got = self.d.f, {}
        if "receipts" not in self.d.collections:
            return got
        for note in self._list("receipts"):
            for line in dig(note, f["rc_lines"]) or []:
                key = (str(dig(line, f["rc_po"])), str(dig(line, f["rc_po_line"])))
                got[key] = got.get(key, Decimal("0")) + _dec(dig(line, f["rc_qty"]))
        return got

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        f, received, out = self.d.f, self._received(), []
        for po in self._list("pos"):
            status = dig(po, f["po_status"])
            if status == self.d.draft_value:
                continue  # drafts stay out of the mirror until a person approves them in the ERP
            po_id, lines = str(dig(po, f["po_id"])), []
            for n, line in enumerate(dig(po, f["po_lines"]) or [], start=1):
                lines.append(ErpPoLine(
                    erp_ref=f"{po_id}/{dig(line, f['line_id'])}", line_no=n, item_code=str(dig(line, f["line_item"]) or ""),
                    description=str(dig(line, f["line_desc"]) or ""), hsn=None, uom=None, qty=_dec(dig(line, f["line_qty"])),
                    rate=_dec(dig(line, f["line_rate"])), amount=_dec(dig(line, f["line_amount"])),
                    tax_rate=_dec(dig(line, f["line_tax"]))))
            net = sum((l.amount for l in lines), Decimal("0"))
            tax = sum(((l.amount * l.tax_rate / 100).quantize(CENT, rounding=ROUND_HALF_UP) for l in lines), Decimal("0"))
            done = bool(lines) and all(received.get((po_id, l.erp_ref.split("/", 1)[1]), Decimal("0")) >= l.qty for l in lines)
            tag = ORRFIN_TAG.search(str(dig(po, f["po_memo"]) or ""))
            out.append(ErpPurchaseOrder(
                erp_ref=po_id, vendor_ref=str(dig(po, f["po_vendor"])), po_date=_day(dig(po, f["po_date"])),
                schedule_date=_day(dig(po, f["po_due"])),
                status="closed" if status == self.d.closed_value else ("to_bill" if done else "open"),
                currency=str(dig(po, f["po_currency"]) or "INR"), net_total=net, tax_total=tax, grand_total=net + tax,
                orrfin_ref=tag.group(1) if tag else None, modified=_stamp(dig(po, f["modified"])), lines=lines,
                po_number=str(dig(po, f["po_number"]) or "") or None))
        return out

    def list_receipts(self) -> list[ErpReceipt]:
        if "receipts" not in self.d.collections:
            return []
        f, out = self.d.f, []
        for note in self._list("receipts"):
            note_id = str(dig(note, f["rc_id"]))
            lines = [ErpReceiptLine(erp_ref=f"{note_id}/{dig(l, f['rc_line_id'])}", item_code=str(dig(l, f["rc_item"]) or ""),
                                    qty_received=_dec(dig(l, f["rc_qty"])), po_ref=str(dig(l, f["rc_po"])),
                                    po_line_ref=f"{dig(l, f['rc_po'])}/{dig(l, f['rc_po_line'])}")
                     for l in dig(note, f["rc_lines"]) or []]
            out.append(ErpReceipt(erp_ref=note_id, vendor_ref=str(dig(note, f["rc_vendor"])),
                                  posting_date=_day(dig(note, f["rc_date"])), status="received",
                                  modified=_stamp(dig(note, f["modified"])), lines=lines))
        return out

    def _lines(self, lines) -> list[dict[str, Any]]:
        f, out = self.d.f, []
        for line in lines:
            row: dict[str, Any] = {}  # `plant` returns the leaf's parent, so fill one root dict per line
            plant(row, f["line_item"], line.item_code)
            plant(row, f["line_qty"], str(line.qty))
            plant(row, f["line_rate"], str(line.rate))
            out.append(row)
        return out

    def create_draft_bill(self, bill: DraftBill) -> Created:
        f, body = self.d.f, {}
        for path, value in ((f["bill_vendor"], bill.vendor_ref), (f["bill_number"], bill.supplier_invoice_no),
                            (f["bill_date"], bill.invoice_date.isoformat()), (f["bill_memo"], f"orrfin:{bill.idempotency_key}"),
                            (f["bill_status"], self.d.draft_value), (f["bill_lines"], self._lines(bill.lines))):
            plant(body, path, value)
        return Created(erp_doc_name=f"Draft bill {dig(self._post('bills', body), f['bill_id'])}")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        f = self.d.f
        rows = [b for b in self._list("bills") if str(dig(b, f["bill_vendor"])) == vendor_ref
                and str(dig(b, f["bill_number"])) == supplier_invoice_no]
        return f"Draft bill {dig(rows[0], f['bill_id'])}" if rows else None

    def create_draft_po(self, po: DraftPo) -> Created:
        f, body = self.d.f, {}
        for path, value in ((f["po_vendor"], po.vendor_ref), (f["po_date"], po.po_date.isoformat()),
                            (f["po_due"], po.schedule_date.isoformat()),
                            (f["po_memo"], f"orrfin:{po.idempotency_key} | {po.request_number}"),
                            (f["po_status"], self.d.draft_value), (f["po_lines"], self._lines(po.lines))):
            plant(body, path, value)
        return Created(erp_doc_name=f"Draft PO {dig(self._post('po_drafts', body), f['po_id'])}")

    def find_po(self, orrfin_key: str) -> str | None:
        f = self.d.f
        rows = [p for p in self._list("po_drafts") if dig(p, f["po_status"]) == self.d.draft_value
                and f"orrfin:{orrfin_key}" in str(dig(p, f["po_memo"]) or "")]
        return f"Draft PO {dig(rows[0], f['po_id'])}" if rows else None

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={}, notes=[f"{self.d.name} is simulated: its data comes from the canonical dataset."])
