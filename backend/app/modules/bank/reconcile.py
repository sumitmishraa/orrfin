"""Bank reconciliation rules (BUILD_PLAN v2.4 change 32; PROMPTS Step 26). Pure: no database, no AI.

1. UTR: the payment's UTR appears in the bank line's reference or narration → matched.
2. Otherwise the same amount, a date within 3 days, and the vendor's first name-word in the narration →
   suggested only; a person accepts or rejects it, because amounts and names can coincide.
Each payment is used at most once; credits are never matched to payments.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

DATE_WINDOW = timedelta(days=3)
_WORD = re.compile(r"[A-Za-z0-9]+")
_GENERIC = {"the", "m", "s", "ms", "pvt", "private", "ltd", "limited", "llp", "india", "co", "and"}


@dataclass(frozen=True)
class BankIn:
    id: str
    txn_date: date
    narration: str
    reference: str
    debit: Decimal


@dataclass(frozen=True)
class PaymentIn:
    id: str
    utr: str | None
    net: Decimal
    paid_on: date
    vendor: str


def _name_word(vendor: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(vendor) if w.lower() not in _GENERIC and len(w) >= 3]
    return words[0] if words else None


def reconcile(lines: list[BankIn], payments: list[PaymentIn]) -> dict[str, tuple[str, str, str]]:
    """bank line id → (payment id, "matched" | "suggested", method)."""
    out: dict[str, tuple[str, str, str]] = {}
    used: set[str] = set()
    debits = [b for b in lines if b.debit > 0]
    for b in debits:
        text = f"{b.reference} {b.narration}".upper()
        for p in payments:
            if p.id not in used and p.utr and p.utr.upper() in text:
                out[b.id] = (p.id, "matched", "utr")
                used.add(p.id)
                break
    for b in debits:
        if b.id in out:
            continue
        narration = b.narration.lower()
        for p in payments:
            word = _name_word(p.vendor)
            if (p.id not in used and p.net == b.debit and abs(p.paid_on - b.txn_date) <= DATE_WINDOW
                    and word and word in narration):
                out[b.id] = (p.id, "suggested", "amount_date_name")
                used.add(p.id)
                break
    return out
