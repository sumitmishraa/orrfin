"""Tax checks that differ by country (BUILD_PLAN §6d). Pure, like the rest of the matching engine.

The legal entity's tax regime picks the checks:
- "in_gst" (India): the supplier tax number is a GSTIN (§6 rule 7) and the place-of-supply rule
  decides between CGST + SGST and IGST (§6 rule 8). Unchanged from rule set 2026.09.1.
- "ae_vat" (UAE): the supplier tax number is a TRN (15 digits starting with 100), there is one
  VAT amount, and there is no place-of-supply split.

A regime never accepts the other regime's tax columns: a UAE invoice charging IGST, or an Indian
invoice charging VAT, is a TAX_TYPE_MISMATCH. To be confirmed by a CA and a UAE tax practitioner.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from app.modules.matching.types import InvoiceIn, RuleResult

TAX_REGIMES = ("in_gst", "ae_vat")

GSTIN_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TRN_FORMAT = re.compile(r"^100[0-9]{12}$")
CENT = Decimal("0.01")


def money(value: Decimal, currency: str) -> str:
    """An amount as people write it: ₹1,234.00 for rupees, "AED 1,234.00" for any other currency."""
    amount = f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,}"
    return f"₹{amount}" if currency == "INR" else f"{currency} {amount}"


def tax_id_name(regime: str) -> str:
    return "TRN" if regime == "ae_vat" else "GSTIN"


def tax_name(regime: str) -> str:
    return "VAT" if regime == "ae_vat" else "GST"


def _gstin_check_char_ok(gstin: str) -> bool:
    total = 0
    for i, ch in enumerate(gstin[:14]):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return gstin[14] == GSTIN_CHARS[(36 - total % 36) % 36]


def tax_id_result(regime: str, tax_id: str | None, invoice_total: Decimal) -> RuleResult:
    """Is the supplier's tax number well formed for this regime? (§6 rule 7, §6d)"""
    tax_id = tax_id or ""
    if regime == "ae_vat":
        if TRN_FORMAT.match(tax_id):
            return RuleResult("trn", "OK", "pass", "The vendor TRN is well formed.")
        return RuleResult("trn", "TRN_INVALID", "fail",
                          f"The vendor TRN “{tax_id}” is not 15 digits starting with 100.", invoice_total)
    if not GSTIN_FORMAT.match(tax_id):
        return RuleResult("gstin", "GSTIN_INVALID", "fail",
                          f"The vendor GSTIN “{tax_id}” is not in a valid GSTIN format.", invoice_total)
    if not _gstin_check_char_ok(tax_id):
        # Advisory only until the check-digit method is verified against an official GSTN source.
        return RuleResult("gstin", "GSTIN_CHECKSUM", "warn",
                          "The GSTIN's last character does not match its check digit (advisory only).")
    return RuleResult("gstin", "OK", "pass", "The vendor GSTIN is well formed.")


def tax_type_result(regime: str, inv: InvoiceIn, po_vendor_tax_id: str | None) -> RuleResult:
    """Does the invoice charge the right kind of tax? (§6 rule 8 for India; §6d for the UAE)"""
    gst = inv.cgst + inv.sgst + inv.igst
    if regime == "ae_vat":
        if gst > 0:
            return RuleResult("tax_type", "TAX_TYPE_MISMATCH", "fail",
                              f"A UAE invoice carries VAT only, but this one charges Indian GST "
                              f"{money(gst, inv.currency)}.", gst)
        return RuleResult("tax_type", "OK", "pass", "The invoice charges VAT only.")

    if inv.vat > 0:
        return RuleResult("tax_type", "TAX_TYPE_MISMATCH", "fail",
                          f"An Indian invoice carries GST, but this one charges VAT {money(inv.vat, inv.currency)}.",
                          inv.vat)
    # Place of supply: same state → CGST + SGST; different state → IGST.
    vendor_state = inv.vendor_gstin[:2] if (inv.vendor_gstin or "")[:2].isdigit() else (po_vendor_tax_id or "")[:2]
    if vendor_state == inv.buyer_state_code:
        if inv.igst > 0:
            return RuleResult("tax_type", "TAX_TYPE_MISMATCH", "fail",
                              f"Vendor and buyer are both in state {vendor_state}, so CGST + SGST applies, "
                              f"but the invoice charges IGST {money(inv.igst, inv.currency)}.", inv.igst)
        return RuleResult("tax_type", "OK", "pass", "Same-state supply taxed as CGST + SGST.")
    if inv.cgst + inv.sgst > 0:
        return RuleResult("tax_type", "TAX_TYPE_MISMATCH", "fail",
                          f"The vendor (state {vendor_state}) is in another state, so IGST applies, but the "
                          f"invoice charges CGST + SGST {money(inv.cgst + inv.sgst, inv.currency)}.",
                          inv.cgst + inv.sgst)
    return RuleResult("tax_type", "OK", "pass", "Inter-state supply taxed as IGST.")
