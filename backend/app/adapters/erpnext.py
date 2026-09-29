"""ERPNext document → Orrfin record translation (BUILD_PLAN §2, §4 adapter rules).

The only place ERPNext field names (supplier_name, gst_hsn_code, purchase_order_item, ...)
may appear. Both the fake adapter (fixtures, Step 4) and the live REST adapter (Step 11)
feed ERPNext documents through these functions, so they behave identically.

ERPNext numbers must be parsed with `parse_float=Decimal` (see `load_erpnext_json`)
so money never passes through float.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.ports.erp import ErpPoLine, ErpPurchaseOrder, ErpReceipt, ErpReceiptLine, ErpVendor

# ERPNext stores `modified` as naive server-local time; an Indian site runs on IST.
ERPNEXT_TIMEZONE = ZoneInfo("Asia/Kolkata")
SUBMITTED = 1  # docstatus: 0 draft, 1 submitted, 2 cancelled

# ERPNext PO status → Orrfin's small vocabulary.
_PO_STATUS = {
    "To Receive and Bill": "open",
    "To Receive": "open",
    "To Bill": "to_bill",
    "Completed": "completed",
    "Closed": "closed",
    "On Hold": "on_hold",
    "Delivered": "to_bill",
}
_GST_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def load_erpnext_json(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _modified(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ERPNEXT_TIMEZONE)


def supplier_to_vendor(doc: dict[str, Any]) -> ErpVendor:
    gstin = (doc.get("gstin") or doc.get("tax_id") or "").strip().upper() or None
    return ErpVendor(
        erp_ref=doc["name"],
        name=doc.get("supplier_name") or doc["name"],
        gstin=gstin,
        # The first two GSTIN digits are the state code (27 = Maharashtra).
        state_code=gstin[:2] if gstin else None,
        modified=_modified(doc["modified"]),
    )


def _item_tax_rate(item: dict[str, Any], doc_taxes: list[dict[str, Any]]) -> Decimal:
    """GST % for a line: from its item tax template ("GST 18% - ODC"), else the document's tax rows."""
    match = _GST_PERCENT.search(item.get("item_tax_template") or "")
    if match:
        return Decimal(match.group(1))
    return sum((_dec(t.get("rate")) for t in doc_taxes if t.get("charge_type") == "On Net Total"), Decimal("0"))


def purchase_order_to_record(doc: dict[str, Any]) -> ErpPurchaseOrder:
    taxes = doc.get("taxes") or []
    return ErpPurchaseOrder(
        erp_ref=doc["name"],
        vendor_ref=doc["supplier"],
        po_date=_date(doc.get("transaction_date")),
        schedule_date=_date(doc.get("schedule_date")),
        status=_PO_STATUS.get(doc.get("status", ""), "open"),
        currency=doc.get("currency") or "INR",
        net_total=_dec(doc.get("net_total")),
        tax_total=_dec(doc.get("total_taxes_and_charges")),
        grand_total=_dec(doc.get("grand_total")),
        orrfin_ref=doc.get("orrfin_ref") or None,
        modified=_modified(doc["modified"]),
        lines=[
            ErpPoLine(
                erp_ref=item["name"],
                line_no=int(item.get("idx") or n),
                item_code=item["item_code"],
                description=item.get("description") or item.get("item_name") or "",
                hsn=item.get("gst_hsn_code"),
                uom=item.get("uom"),
                qty=_dec(item.get("qty")),
                rate=_dec(item.get("rate")),
                amount=_dec(item.get("amount")),
                tax_rate=_item_tax_rate(item, taxes),
            )
            for n, item in enumerate(doc.get("items") or [], start=1)
        ],
    )


def purchase_receipt_to_record(doc: dict[str, Any]) -> ErpReceipt:
    return ErpReceipt(
        erp_ref=doc["name"],
        vendor_ref=doc["supplier"],
        posting_date=_date(doc.get("posting_date")),
        status=doc.get("status") or "",
        modified=_modified(doc["modified"]),
        lines=[
            ErpReceiptLine(
                erp_ref=item["name"],
                item_code=item["item_code"],
                # `qty` is the accepted quantity; rejected goods don't count as received.
                qty_received=_dec(item.get("qty")),
                po_ref=item.get("purchase_order"),
                po_line_ref=item.get("purchase_order_item"),
            )
            for item in doc.get("items") or []
        ],
    )


def is_submitted(doc: dict[str, Any]) -> bool:
    return int(doc.get("docstatus", 0)) == SUBMITTED
