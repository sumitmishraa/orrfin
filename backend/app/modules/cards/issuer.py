"""The card-issuer port and the mock issuer behind it (BUILD_PLAN change 46, ADR 0008).

`CardIssuer` is the shape a real issuing partner would be plugged in behind. Today only
`MockCardIssuer` exists: it makes a reference and a last-four from random numbers, and never
produces or stores a full card number. Orrfin keeps the rules (limit, merchant lock, expiry,
freeze); the issuer only says yes or no on the card it was told about.
"""

import secrets
from datetime import date
from decimal import Decimal
from typing import Protocol


class CardIssuer(Protocol):
    def issue(self, *, currency: str, limit: Decimal, expires_on: date) -> tuple[str, str]:
        """Create a virtual card. Returns (issuer reference, last four digits)."""
        ...

    def set_state(self, issuer_ref: str, state: str) -> None:
        """Tell the issuer the card is active, frozen or closed."""
        ...


class MockCardIssuer:
    """A simulated issuer: nothing leaves Orrfin, and no card can be used anywhere real."""

    def issue(self, *, currency: str, limit: Decimal, expires_on: date) -> tuple[str, str]:
        return f"SIMCARD-{secrets.token_hex(8).upper()}", f"{secrets.randbelow(10_000):04d}"

    def set_state(self, issuer_ref: str, state: str) -> None:
        return None


def get_issuer() -> CardIssuer:
    return MockCardIssuer()
