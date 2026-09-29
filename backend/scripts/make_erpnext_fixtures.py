"""Generate the fake ERPNext fixtures in seed/erpnext/ (PROMPTS Step 4, BUILD_PLAN §3 "fake ERPNext first").

Owns: suppliers.json, purchase_orders.json, purchase_receipts.json. Each file is shaped
like ERPNext's REST reply ({"data": [...]}), holding full documents as returned by
GET /api/resource/<DocType>/<name>, child tables included. The buyer org sits in
Maharashtra (state 27): same-state suppliers charge CGST 9% + SGST 9%, others IGST 18%.
All companies and GSTINs are fictional; GSTINs carry a valid check character.

Run from the repo root:  backend\\.venv\\Scripts\\python backend\\scripts\\make_erpnext_fixtures.py
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "seed" / "erpnext"
COMPANY = "Orrfin Demo Co"
BUYER_STATE = "27"
GST_RATE = Decimal("18")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CENT = Decimal("0.01")


def gstin(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return first14 + GSTIN_CHARS[(36 - total % 36) % 36]


def row_name(*parts: str) -> str:
    """ERPNext child rows have short random names; these are deterministic stand-ins."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def num(value: Decimal) -> float | int:
    # ERPNext's JSON carries numbers, not strings. The adapter reads them back as Decimal
    # via their string form, so these fixed two-decimal values survive exactly.
    return int(value) if value == value.to_integral_value() else float(value)


SUPPLIERS = [
    # (name, supplier_group, gstin first 14, modified)
    ("Shreeji Office Supplies Pvt Ltd", "Stationery", "27AABCS4821K1Z", "2026-09-18 10:12:04.000000"),
    ("Kaveri IT Solutions LLP", "Hardware", "29AAKFK3310P1Z", "2026-09-18 10:15:41.000000"),
    ("Northwind Networks India Pvt Ltd", "Hardware", "07AADCN5566Q1Z", "2026-09-18 10:19:02.000000"),
    ("Deccan Facility Services Pvt Ltd", "Services", "27AAECD9082R1Z", "2026-09-18 10:22:37.000000"),
    ("Sahyadri Print & Stationery", "Stationery", "27ABNPS1204H1Z", "2026-09-18 10:25:55.000000"),
]

# (po number, supplier index, date, schedule date, lines: (item_code, item_name, hsn, uom, qty, rate),
#  receipts: [(receipt number, posting date, {line index: qty received})], closed?)
PURCHASE_ORDERS = [
    (1, 0, "2026-09-01", "2026-09-08",
     [("STAT-A4-75", "A4 copier paper 75 GSM (500 sheets)", "4802", "Ream", 100, "285.00"),
      ("STAT-PEN-BLU50", "Ball pens, blue (box of 50)", "9608", "Box", 40, "450.00")],
     [(1, "2026-09-07", {0: 100, 1: 40})], False),
    (2, 1, "2026-09-02", "2026-09-15",
     [("IT-LAP-14-I5", "Laptop 14in, Core i5, 16 GB RAM, 512 GB SSD", "8471", "Nos", 5, "78500.00"),
      ("IT-DOCK-USBC", "USB-C docking station", "8473", "Nos", 5, "9800.00")],
     [(2, "2026-09-12", {0: 3, 1: 5})], False),
    (3, 2, "2026-09-05", "2026-09-30",
     [("NET-AP-WIFI6", "Wi-Fi 6 access point", "8517", "Nos", 10, "14200.00"),
      ("NET-SW-24POE", "24-port PoE switch", "8517", "Nos", 2, "38500.00")],
     [], False),
    (4, 3, "2026-09-01", "2026-09-30",
     [("SVC-HOUSEKEEP", "Housekeeping services, September 2026", "9985", "Month", 1, "125000.00")],
     [(3, "2026-09-30", {0: 1})], False),
    (5, 4, "2026-09-03", "2026-09-17",
     [("PRN-VCARD", "Visiting cards, 100 per box", "4911", "Box", 20, "650.00"),
      ("PRN-LETTERHEAD", "Letterheads, 500 sheets", "4911", "Ream", 10, "1450.00")],
     [(4, "2026-09-09", {0: 10}), (5, "2026-09-16", {0: 10, 1: 10})], False),
    (6, 1, "2026-09-08", "2026-09-22",
     [("IT-MON-27", "27in IPS monitor", "8528", "Nos", 8, "16900.00")],
     [(6, "2026-09-20", {0: 6})], False),
    (7, 0, "2026-08-20", "2026-08-31",
     [("STAT-BOXFILE", "Box files, laminated", "4820", "Nos", 200, "95.50")],
     [(7, "2026-08-30", {0: 150})], True),
    (8, 2, "2026-09-10", "2026-09-19",
     [("NET-FW-APPL", "Next-generation firewall appliance", "8517", "Nos", 1, "215000.00"),
      ("NET-FW-AMC", "Firewall support and updates, 12 months", "9987", "Nos", 1, "36000.00")],
     [(8, "2026-09-18", {0: 1, 1: 1})], False),
]


def build() -> tuple[list, list, list]:
    suppliers = []
    for name, group, first14, modified in SUPPLIERS:
        suppliers.append({
            "name": name, "supplier_name": name, "supplier_group": group, "supplier_type": "Company",
            "country": "India", "gstin": gstin(first14), "gst_category": "Registered Regular",
            "disabled": 0, "docstatus": 0, "modified": modified,
        })

    orders, receipts = [], []
    for number, supplier_index, date, schedule, lines, po_receipts, closed in PURCHASE_ORDERS:
        supplier = suppliers[supplier_index]
        po_name = f"PUR-ORD-2026-{number:05d}"
        same_state = supplier["gstin"][:2] == BUYER_STATE
        received = {i: sum(r[2].get(i, 0) for r in po_receipts) for i in range(len(lines))}
        items, net_total = [], Decimal("0")
        for idx, (code, item_name, hsn, uom, qty, rate) in enumerate(lines):
            amount = money(Decimal(qty) * Decimal(rate))
            net_total += amount
            items.append({
                "name": row_name(po_name, code), "idx": idx + 1, "item_code": code, "item_name": item_name,
                "description": item_name, "gst_hsn_code": hsn, "uom": uom, "qty": qty,
                "received_qty": received[idx], "rate": num(Decimal(rate)), "amount": num(amount),
                "item_tax_template": "GST 18% - ODC", "schedule_date": schedule,
            })
        if same_state:
            half = money(net_total * GST_RATE / 2 / 100)
            taxes = [
                {"idx": 1, "charge_type": "On Net Total", "account_head": "Input Tax CGST - ODC",
                 "rate": 9, "tax_amount": num(half), "description": "CGST"},
                {"idx": 2, "charge_type": "On Net Total", "account_head": "Input Tax SGST - ODC",
                 "rate": 9, "tax_amount": num(half), "description": "SGST"},
            ]
            tax_total = half * 2
        else:
            tax_total = money(net_total * GST_RATE / 100)
            taxes = [{"idx": 1, "charge_type": "On Net Total", "account_head": "Input Tax IGST - ODC",
                      "rate": 18, "tax_amount": num(tax_total), "description": "IGST"}]
        ordered_qty = sum(line[4] for line in lines)
        per_received = round(100 * sum(received.values()) / ordered_qty, 2)
        if closed:
            status = "Closed"
        elif per_received >= 100:
            status = "To Bill"
        else:
            status = "To Receive and Bill"
        orders.append({
            "name": po_name, "supplier": supplier["name"], "company": COMPANY,
            "transaction_date": date, "schedule_date": schedule, "currency": "INR",
            "status": status, "docstatus": 1, "per_received": per_received, "per_billed": 0,
            "net_total": num(net_total), "total_taxes_and_charges": num(tax_total),
            "grand_total": num(net_total + tax_total), "orrfin_ref": None,
            "modified": f"{date} 16:30:00.000000", "items": items, "taxes": taxes,
        })
        for receipt_number, posting_date, quantities in po_receipts:
            pr_name = f"MAT-PRE-2026-{receipt_number:05d}"
            pr_items = []
            for idx, qty in quantities.items():
                po_item = items[idx]
                pr_items.append({
                    "name": row_name(pr_name, po_item["item_code"]), "idx": len(pr_items) + 1,
                    "item_code": po_item["item_code"], "item_name": po_item["item_name"],
                    "qty": qty, "received_qty": qty, "rejected_qty": 0, "uom": po_item["uom"],
                    "rate": po_item["rate"], "purchase_order": po_name, "purchase_order_item": po_item["name"],
                })
            receipts.append({
                "name": pr_name, "supplier": supplier["name"], "company": COMPANY,
                "posting_date": posting_date, "status": "To Bill", "docstatus": 1,
                "modified": f"{posting_date} 18:05:00.000000", "items": pr_items,
            })
    return suppliers, orders, receipts


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suppliers, orders, receipts = build()
    for filename, docs in (("suppliers.json", suppliers), ("purchase_orders.json", orders),
                           ("purchase_receipts.json", receipts)):
        (OUT_DIR / filename).write_text(json.dumps({"data": docs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(suppliers)} suppliers, {len(orders)} purchase orders, {len(receipts)} receipts to {OUT_DIR}")


if __name__ == "__main__":
    main()
