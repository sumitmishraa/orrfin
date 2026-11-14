"""Currency conversion (BUILD_PLAN §5 `fx_rates`). Pure: no database, no AI.

A rate always comes from the table a named person filled in; nothing here looks one up online
or estimates it. Converted money is rounded once, half-up, to 2 decimals.
"""

from decimal import ROUND_HALF_UP, Decimal

CURRENCIES = ("INR", "AED", "USD", "EUR")
CENT = Decimal("0.01")


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    """`amount` in the base currency → the quote currency, where 1 base = `rate` quote."""
    if not isinstance(amount, Decimal) or not isinstance(rate, Decimal):
        # A float here would silently lose paise; refuse it instead of rounding it away.
        raise TypeError("Money and exchange rates must be Decimal, never float.")
    if rate <= 0:
        raise ValueError("An exchange rate must be greater than zero.")
    return (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)
