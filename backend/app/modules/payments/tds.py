"""TDS on vendor payments (BUILD_PLAN §6c; PROMPTS Step 25). Pure, versioned, Decimal money.

TO BE CONFIRMED BY A CA before any pilot (§12): the rates, thresholds and the simplifications below.
- 194C contractors: 1% individual/HUF, 2% others; deduct when one payment is above ₹30,000 or the
  year's payments to the vendor go above ₹1,00,000 (then on this payment).
- 194J fees: 10% professional, 2% technical services; deduct when the year's payments go above ₹50,000.
- 194Q purchase of goods: 0.1% on the part of the year's purchases above ₹50,00,000.
- No valid PAN (206AA): at least 20%, or 5% under 194Q.
- Base: the invoice value before GST, when GST is shown separately. Rounded to the nearest rupee.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

TDS_RULE_SET_VERSION = "2026.10.1"
SECTIONS = ("194C", "194J", "194Q")
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
ZERO = Decimal("0")
RUPEE = Decimal("1")

C_SINGLE_LIMIT = Decimal("30000")
C_YEAR_LIMIT = Decimal("100000")
J_YEAR_LIMIT = Decimal("50000")
Q_YEAR_LIMIT = Decimal("5000000")
NO_PAN_RATE = Decimal("20")
NO_PAN_RATE_194Q = Decimal("5")


@dataclass(frozen=True)
class TdsInput:
    section: str | None
    payee_type: Literal["individual", "company", "other"]
    pan: str | None
    base: Decimal  # this payment's value before GST
    paid_before_in_fy: Decimal  # earlier payments to this vendor under the same section, this financial year
    j_kind: Literal["professional", "technical"] = "professional"


@dataclass(frozen=True)
class TdsResult:
    section: str | None
    rate: Decimal  # percent
    taxable: Decimal  # the part of the base TDS applies to
    tds: Decimal
    reason: str
    rule_set_version: str = TDS_RULE_SET_VERSION


def valid_pan(pan: str | None) -> bool:
    return bool(pan and _PAN.match(pan.strip().upper()))


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(RUPEE, ROUND_HALF_UP).quantize(Decimal("0.01"))


def compute_tds(inp: TdsInput) -> TdsResult:
    if inp.section not in SECTIONS:
        return TdsResult(None, ZERO, ZERO, Decimal("0.00"), "No TDS section for this vendor.")
    year_total = inp.paid_before_in_fy + inp.base
    no_pan = not valid_pan(inp.pan)
    if inp.section == "194C":
        rate = Decimal("1") if inp.payee_type == "individual" else Decimal("2")
        applies = inp.base > C_SINGLE_LIMIT or year_total > C_YEAR_LIMIT
        taxable = inp.base if applies else ZERO
        reason = ("194C: above ₹30,000 in one payment or ₹1,00,000 in the year." if applies
                  else "194C: below both limits, no TDS yet.")
    elif inp.section == "194J":
        rate = Decimal("10") if inp.j_kind == "professional" else Decimal("2")
        applies = year_total > J_YEAR_LIMIT
        taxable = inp.base if applies else ZERO
        reason = "194J: above ₹50,000 in the year." if applies else "194J: below ₹50,000 in the year, no TDS yet."
    else:
        rate = Decimal("0.1")
        taxable = max(ZERO, year_total - Q_YEAR_LIMIT) - max(ZERO, inp.paid_before_in_fy - Q_YEAR_LIMIT)
        reason = "194Q: on purchases above ₹50,00,000 in the year." if taxable else "194Q: below ₹50,00,000, no TDS."
    if no_pan:
        rate = max(rate, NO_PAN_RATE_194Q if inp.section == "194Q" else NO_PAN_RATE)
        reason += " No valid PAN: higher rate under section 206AA."
    return TdsResult(inp.section, rate, taxable, _round(taxable * rate / 100), reason)
