"""Render the canonical dataset as ERPNext documents (BUILD_PLAN §4 "one canonical dataset rendered into
each ERP's native format"; PROMPTS Step 4 fixtures, Step 12 renderer).

Output is shaped like ERPNext REST replies ({"data": [...]}) holding full documents as returned by
GET /api/resource/<DocType>/<name>, child tables included. `scripts/make_erpnext_fixtures.py` writes
it to seed/erpnext/, and a contract test checks the committed files still equal this output.
"""

import hashlib
from decimal import Decimal
from typing import Any

from app.erp_demo.canonical import COMPANY, Dataset, PurchaseOrder, dataset

# ERPNext PO status names, from Orrfin's (inverse of erpnext._PO_STATUS for the statuses the demo uses).
_STATUS = {"closed": "Closed", "to_bill": "To Bill", "open": "To Receive and Bill"}


def row_name(*parts: str) -> str:
    """ERPNext child rows have short random names; these are deterministic stand-ins."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def num(value: Decimal) -> float | int:
    # ERPNext's JSON carries numbers, not strings. The adapter reads them back as Decimal
    # via their string form, so these fixed two-decimal values survive exactly.
    return int(value) if value == value.to_integral_value() else float(value)


def supplier_doc(vendor) -> dict[str, Any]:
    return {
        "name": vendor.name, "supplier_name": vendor.name, "supplier_group": vendor.group,
        "supplier_type": "Company", "country": "India", "gstin": vendor.gstin,
        "gst_category": "Registered Regular", "disabled": 0, "docstatus": 0,
        "modified": vendor.modified.strftime("%Y-%m-%d %H:%M:%S.000000"),
    }


def _taxes(po: PurchaseOrder) -> list[dict[str, Any]]:
    if po.vendor.same_state:
        return [
            {"idx": 1, "charge_type": "On Net Total", "account_head": "Input Tax CGST - ODC",
             "rate": 9, "tax_amount": num(po.cgst), "description": "CGST"},
            {"idx": 2, "charge_type": "On Net Total", "account_head": "Input Tax SGST - ODC",
             "rate": 9, "tax_amount": num(po.sgst), "description": "SGST"},
        ]
    return [{"idx": 1, "charge_type": "On Net Total", "account_head": "Input Tax IGST - ODC",
             "rate": 18, "tax_amount": num(po.igst), "description": "IGST"}]


def purchase_order_doc(po: PurchaseOrder) -> dict[str, Any]:
    items = [{
        "name": row_name(po.number, line.item_code), "idx": idx + 1, "item_code": line.item_code,
        "item_name": line.item_name, "description": line.item_name, "gst_hsn_code": line.hsn, "uom": line.uom,
        "qty": num(line.qty), "received_qty": num(po.received(idx)), "rate": num(line.rate),
        "amount": num(line.amount), "item_tax_template": "GST 18% - ODC", "schedule_date": po.schedule_date.isoformat(),
    } for idx, line in enumerate(po.lines)]
    return {
        "name": po.number, "supplier": po.vendor.name, "company": COMPANY,
        "transaction_date": po.po_date.isoformat(), "schedule_date": po.schedule_date.isoformat(),
        "currency": "INR", "status": _STATUS[po.status], "docstatus": 1,
        "per_received": float(po.per_received),  # ERPNext sends percentages as floats (100.0)
        "per_billed": 0, "net_total": num(po.net_total), "total_taxes_and_charges": num(po.tax_total),
        "grand_total": num(po.grand_total), "orrfin_ref": None,
        "modified": po.modified.strftime("%Y-%m-%d %H:%M:%S.000000"), "items": items, "taxes": _taxes(po),
    }


def purchase_receipt_docs(po: PurchaseOrder) -> list[dict[str, Any]]:
    docs = []
    for receipt in po.receipts:
        items = []
        for idx, qty in receipt.quantities.items():
            line = po.lines[idx]
            items.append({
                "name": row_name(receipt.number, line.item_code), "idx": len(items) + 1,
                "item_code": line.item_code, "item_name": line.item_name, "qty": num(qty), "received_qty": num(qty),
                "rejected_qty": 0, "uom": line.uom, "rate": num(line.rate), "purchase_order": po.number,
                "purchase_order_item": row_name(po.number, line.item_code),
            })
        docs.append({
            "name": receipt.number, "supplier": po.vendor.name, "company": COMPANY,
            "posting_date": receipt.posting_date.isoformat(), "status": "To Bill", "docstatus": 1,
            "modified": receipt.modified.strftime("%Y-%m-%d %H:%M:%S.000000"), "items": items,
        })
    return docs


def render(data: Dataset | None = None) -> dict[str, list[dict[str, Any]]]:
    """{filename: documents} for seed/erpnext/."""
    data = data or dataset()
    return {
        "suppliers.json": [supplier_doc(v) for v in data.vendors],
        "purchase_orders.json": [purchase_order_doc(po) for po in data.purchase_orders],
        "purchase_receipts.json": [doc for po in data.purchase_orders for doc in purchase_receipt_docs(po)],
    }
