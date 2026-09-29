"""Generate one synthetic GST invoice PDF plus its ground-truth JSON (BUILD_PLAN §7, Step 2 spike).

Owns: seed/invoices/INV-SAMPLE-001.pdf and INV-SAMPLE-001.expected.json.
The vendor, buyer and GSTINs are invented. The GSTINs are format-valid,
including the check character, so the later GSTIN validator (§7) accepts them.

Run from the repo root:  backend\\.venv\\Scripts\\python backend\\scripts\\make_sample_invoice.py
"""

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "seed" / "invoices"
STEM = "INV-SAMPLE-001"

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CENT = Decimal("0.01")


def gstin_with_checksum(first14: str) -> str:
    """Append the official GSTIN check character (mod-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return first14 + GSTIN_CHARS[(36 - total % 36) % 36]


# Both parties are in Maharashtra (state code 27): an intra-state supply is taxed
# as CGST + SGST (half the GST rate each), not IGST.
VENDOR = {
    "name": "Shreeji Office Supplies Pvt Ltd",
    "address": "Unit 14, Laxmi Industrial Estate, Andheri (W), Mumbai 400053",
    "gstin": gstin_with_checksum("27AABCS4821K1Z"),
}
BUYER = {
    "name": "Orrfin Demo Buyer Pvt Ltd",
    "address": "3rd Floor, Baner Road, Pune 411045",
    "gstin": gstin_with_checksum("27AADCO7734M1Z"),
}
INVOICE_NO = "SOS/2026-27/0187"
INVOICE_DATE = "2026-09-22"  # ISO; printed as 22-09-2026 on the PDF, as Indian invoices do
PO_REFERENCE = "PO-2026-0042"
GST_RATE = Decimal("18")

LINES = [
    # description, HSN, qty, unit, rate
    ("A4 copier paper 75 GSM (500 sheets)", "4802", Decimal("50"), "Ream", Decimal("285.00")),
    ("Ball pens, blue (box of 50)", "9608", Decimal("20"), "Box", Decimal("450.00")),
    ("Box files, laminated", "4820", Decimal("40"), "Nos", Decimal("95.50")),
]


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def build_expected() -> dict:
    lines = []
    for description, hsn, qty, _unit, rate in LINES:
        lines.append({
            "description": description,
            "hsn": hsn,
            "qty": str(qty),
            "rate": str(rate),
            "amount": str(money(qty * rate)),
        })
    subtotal = money(sum(Decimal(line["amount"]) for line in lines))
    half_rate = GST_RATE / 2 / 100
    cgst = money(subtotal * half_rate)
    sgst = money(subtotal * half_rate)
    return {
        "vendor_name": VENDOR["name"],
        "vendor_gstin": VENDOR["gstin"],
        "buyer_gstin": BUYER["gstin"],
        "invoice_no": INVOICE_NO,
        "invoice_date": INVOICE_DATE,
        "po_reference": PO_REFERENCE,
        "currency": "INR",
        "lines": lines,
        "subtotal": str(subtotal),
        "cgst": str(cgst),
        "sgst": str(sgst),
        "igst": "0.00",
        "total": str(subtotal + cgst + sgst),
    }


def inr(value: str) -> str:
    return f"{Decimal(value):,.2f}"


def build_pdf(expected: dict, path: Path) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Tax Invoice {INVOICE_NO}", author="Synthetic test data")
    story = [
        Paragraph(f"<b>{VENDOR['name']}</b>", styles["Title"]),
        Paragraph(f"{VENDOR['address']}<br/>GSTIN: {VENDOR['gstin']}", styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph("<b>TAX INVOICE</b>", styles["Heading2"]),
    ]
    day, month, year = INVOICE_DATE[8:10], INVOICE_DATE[5:7], INVOICE_DATE[0:4]
    header = Table([
        ["Invoice No:", INVOICE_NO, "Invoice Date:", f"{day}-{month}-{year}"],
        ["PO Reference:", PO_REFERENCE, "Place of Supply:", "27 - Maharashtra"],
    ], colWidths=[28 * mm, 55 * mm, 32 * mm, 45 * mm])
    story += [header, Spacer(1, 4 * mm),
              Paragraph(f"<b>Bill To:</b> {BUYER['name']}<br/>{BUYER['address']}<br/>"
                        f"GSTIN: {BUYER['gstin']}", styles["Normal"]),
              Spacer(1, 6 * mm)]

    rows = [["#", "Description", "HSN", "Qty", "Unit", "Rate (INR)", "Amount (INR)"]]
    for i, ((_d, _h, _q, unit, _r), line) in enumerate(zip(LINES, expected["lines"]), start=1):
        rows.append([str(i), line["description"], line["hsn"], line["qty"], unit,
                     inr(line["rate"]), inr(line["amount"])])
    lines_table = Table(rows, colWidths=[8 * mm, 68 * mm, 16 * mm, 12 * mm, 14 * mm, 24 * mm, 28 * mm])
    lines_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    totals = Table([
        ["Taxable value", inr(expected["subtotal"])],
        ["CGST @ 9%", inr(expected["cgst"])],
        ["SGST @ 9%", inr(expected["sgst"])],
        ["Invoice total (INR)", inr(expected["total"])],
    ], colWidths=[50 * mm, 30 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("LINEABOVE", (0, 3), (-1, 3), 0.8, colors.black),
    ]))
    story += [lines_table, Spacer(1, 4 * mm), totals, Spacer(1, 10 * mm),
              Paragraph("SYNTHETIC TEST DOCUMENT - not a real invoice.", styles["Italic"])]
    doc.build(story)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    expected = build_expected()
    build_pdf(expected, OUT_DIR / f"{STEM}.pdf")
    (OUT_DIR / f"{STEM}.expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DIR / (STEM + '.pdf')} and .expected.json (total INR {expected['total']})")


if __name__ == "__main__":
    main()
