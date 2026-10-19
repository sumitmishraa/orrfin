"""Payment-risk rules (BUILD_PLAN §6b; PROMPTS Step 25). Pure and versioned, like the matching rules.

Zip runs "payment risk" checks before money leaves; DualEntry flags anomalies. Here every rule is
deterministic and explained in plain words:
- block: the payment cannot be submitted until the cause is fixed;
- hold: the payment may go ahead only with the approver's written reason.
Bank-detail changes are the classic fraud route, so they get both a maker-checker verification
(elsewhere) and a 30-day hold here.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.modules.payments.tds import SECTIONS, valid_pan

PAYMENT_RULE_SET_VERSION = "2026.10.1"
RECENT_BANK_CHANGE = timedelta(days=30)


@dataclass(frozen=True)
class PaymentFacts:
    invoice_status: str
    invoice_total: Decimal
    already_paid: Decimal  # gross already paid or in another live payment run
    gross: Decimal  # what this payment line settles (before TDS)
    has_profile: bool
    bank_verified: bool
    bank_changed_at: datetime | None
    bank_shared_with_other_vendor: bool
    tds_section: str | None
    pan: str | None
    first_payment: bool
    bill_confirmed_in_erp: bool
    missing_from_gstr2b: bool | None  # None = no GSTR-2B imported for that period yet
    now: datetime


def _r(code: str, level: str, message: str) -> dict[str, Any]:
    return {"code": code, "level": level, "message": message}


def check_payment(f: PaymentFacts) -> list[dict[str, Any]]:
    out = []
    if f.invoice_status != "approved":
        out.append(_r("INVOICE_NOT_APPROVED", "block", "Only an approved invoice can be paid."))
    if f.already_paid >= f.invoice_total:
        out.append(_r("ALREADY_PAID", "block", "This invoice is already paid or in another payment run."))
    elif f.gross > f.invoice_total - f.already_paid:
        out.append(_r("AMOUNT_EXCEEDS_INVOICE", "block",
                      f"Paying ₹{f.gross:,.2f} would exceed what is left on the invoice (₹{f.invoice_total - f.already_paid:,.2f})."))
    if not f.has_profile:
        out.append(_r("NO_PAYMENT_PROFILE", "block", "The vendor has no bank details in Orrfin."))
    else:
        if not f.bank_verified:
            out.append(_r("BANK_UNVERIFIED", "block", "The vendor's bank details were changed and not yet verified by a second person."))
        if f.bank_shared_with_other_vendor:
            out.append(_r("BANK_SHARED", "block", "Another vendor uses the same bank account."))
        if f.bank_changed_at and f.now - f.bank_changed_at < RECENT_BANK_CHANGE:
            out.append(_r("BANK_CHANGED_RECENTLY", "hold",
                          "Bank details changed in the last 30 days: confirm with the vendor by phone before paying."))
        if f.tds_section in SECTIONS and not valid_pan(f.pan):
            out.append(_r("PAN_MISSING", "hold", "No valid PAN: TDS is deducted at the higher 206AA rate."))
    if f.first_payment:
        out.append(_r("FIRST_PAYMENT", "hold", "First payment to this vendor."))
    if not f.bill_confirmed_in_erp:
        out.append(_r("BILL_NOT_IN_ERP", "hold", "The bill is not yet confirmed as a draft in the ERP."))
    if f.missing_from_gstr2b:
        out.append(_r("NOT_IN_GSTR2B", "hold", "The vendor has not reported this invoice in GSTR-2B: input tax credit is at risk."))
    return out


def has_block(results: list[dict[str, Any]]) -> bool:
    return any(r["level"] == "block" for r in results)


def holds(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r["level"] == "hold"]
