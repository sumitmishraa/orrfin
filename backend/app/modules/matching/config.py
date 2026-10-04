"""Matching tolerances, rule-set version and risk weights (BUILD_PLAN §6).

Change a tolerance here only: the values are stored with every match result, so an old
decision can always be re-explained with the numbers it used. To be reviewed by a CA (§11).
"""

from dataclasses import asdict, dataclass
from decimal import Decimal

RULE_SET_VERSION = "2026.09.1"

# PO statuses that still accept invoices (Orrfin's vocabulary, from adapters/erpnext.py).
OPEN_PO_STATUSES = ("open", "to_bill")


@dataclass(frozen=True)
class Tolerances:
    price_pct: Decimal = Decimal("0.02")  # rule 3: invoice rate within 2% of the PO rate
    pairing_rate_pct: Decimal = Decimal("0.02")  # rule 1c: HSN + rate within 2% to pair a line
    arithmetic_abs: Decimal = Decimal("1.00")  # rules 4-5: invoice-level round-off accepted up to ₹1.00

    def as_json(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}


# Fixed weights for the risk score (0-100, capped). Higher = more likely money leaves wrongly.
RISK_WEIGHTS = {
    "DUPLICATE_BLOCKING": 40,
    "VENDOR_MISMATCH": 35,
    "GSTIN_INVALID": 30,
    "PO_NOT_FOUND": 30,
    "PO_NOT_OPEN": 30,
    "QTY_EXCEEDS_RECEIPT": 25,
    "PRICE_VARIANCE": 20,
    "TAX_TYPE_MISMATCH": 20,
    "ARITHMETIC_MISMATCH": 20,
    "LINE_UNPAIRED": 15,
    "DUPLICATE_SUSPECTED": 10,
    "GSTIN_CHECKSUM": 5,
}
