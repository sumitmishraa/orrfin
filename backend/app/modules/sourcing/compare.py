"""Compare supplier quotes for one RFQ (BUILD_PLAN §6f). Pure: plain data in, a ranked table out.

Landed cost = Σ(quantity × rate) + tax + freight, in the RFQ's currency. A quote in another
currency is converted with the exchange rate a person entered for the RFQ's closing date and is
marked "converted"; with no such rate the quote is shown but not scored, never estimated.

The score uses the weights saved on the RFQ before it opened, and every part of it is shown
with its arithmetic. It is a recommendation only: a named person awards, and must write a
reason when the award is not the top score. AI is not involved anywhere in this file.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.modules.entities.fx import convert

DEFAULT_WEIGHTS = {"price": 60, "delivery": 20, "payment_terms": 10, "supplier_risk": 10}
CENT = Decimal("0.01")
ZERO = Decimal("0")


@dataclass
class QuoteLineIn:
    qty: Decimal
    rate: Decimal
    tax_rate: Decimal  # per cent, e.g. 18


@dataclass
class QuoteIn:
    id: str
    supplier_name: str
    currency: str
    lines: list[QuoteLineIn]
    freight: Decimal
    payment_terms_days: int
    delivery_days: int
    # The supplier's risk score (0 best, 100 worst) from its last assessment; None if never assessed.
    risk_score: int | None = None
    # 1 quote-currency unit = fx_rate RFQ-currency units, as entered for the closing date. None if not entered.
    fx_rate: Decimal | None = None


@dataclass
class ComparedQuote:
    quote_id: str
    supplier_name: str
    currency: str
    subtotal: Decimal
    tax: Decimal
    freight: Decimal
    landed_cost: Decimal | None  # in the RFQ currency; None when it could not be converted
    converted: bool
    delivery_days: int
    payment_terms_days: int
    risk_score: int | None
    points: dict[str, Decimal] = field(default_factory=dict)
    arithmetic: dict[str, str] = field(default_factory=dict)
    score: Decimal | None = None
    note: str | None = None


def weight_problems(weights: dict[str, int]) -> list[str]:
    """Why these weights cannot be saved. Empty when they can."""
    problems = []
    if set(weights) != set(DEFAULT_WEIGHTS):
        problems.append(f"Give a weight for each of: {', '.join(DEFAULT_WEIGHTS)}.")
    elif any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in weights.values()):
        problems.append("Each weight must be a whole number of 0 or more.")
    elif sum(weights.values()) != 100:
        problems.append(f"The weights must add up to 100 (they add up to {sum(weights.values())}).")
    return problems


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _priced(quote: QuoteIn, rfq_currency: str) -> ComparedQuote:
    subtotal = sum((line.qty * line.rate for line in quote.lines), ZERO)
    # Tax per line, rounded half-up, as in the invoice rules (§6 rule 5).
    tax = sum((_money(line.qty * line.rate * line.tax_rate / 100) for line in quote.lines), ZERO)
    total = _money(subtotal) + tax + _money(quote.freight)
    row = ComparedQuote(quote_id=quote.id, supplier_name=quote.supplier_name, currency=quote.currency,
                        subtotal=_money(subtotal), tax=tax, freight=_money(quote.freight), landed_cost=total,
                        converted=False, delivery_days=quote.delivery_days,
                        payment_terms_days=quote.payment_terms_days, risk_score=quote.risk_score)
    if quote.currency != rfq_currency:
        if quote.fx_rate is None:
            row.landed_cost = None
            row.note = (f"Quoted in {quote.currency}. No {quote.currency} to {rfq_currency} rate was entered for "
                        "the closing date, so this quote is not scored.")
        else:
            row.landed_cost, row.converted = convert(total, quote.fx_rate), True
            row.note = f"Converted from {quote.currency} {total:,} at {quote.fx_rate.normalize():f}."
    return row


def compare(quotes: list[QuoteIn], rfq_currency: str, weights: dict[str, int]) -> list[ComparedQuote]:
    """Every quote priced and scored, best score first. Quotes that cannot be scored come last."""
    problems = weight_problems(weights)
    if problems:
        raise ValueError(" ".join(problems))
    rows = [_priced(quote, rfq_currency) for quote in quotes]
    scored = [r for r in rows if r.landed_cost is not None]
    if scored:
        lowest_cost = min(r.landed_cost for r in scored)
        fastest = min(max(r.delivery_days, 1) for r in scored)
        longest_terms = max(r.payment_terms_days for r in scored)
    for row in scored:
        days = max(row.delivery_days, 1)  # same-day delivery counts as one day, so nothing divides by zero
        parts = {
            # The cheapest quote gets the full price weight; others get it in proportion.
            "price": (Decimal(weights["price"]) * lowest_cost / row.landed_cost if row.landed_cost > 0 else ZERO,
                      f"{weights['price']} × {lowest_cost:,} ÷ {row.landed_cost:,}"),
            "delivery": (Decimal(weights["delivery"]) * fastest / days,
                         f"{weights['delivery']} × {fastest} ÷ {days} days"),
            # Longer payment terms are better for the buyer.
            "payment_terms": (Decimal(weights["payment_terms"]) * row.payment_terms_days / longest_terms
                              if longest_terms > 0 else Decimal(weights["payment_terms"]),
                              f"{weights['payment_terms']} × {row.payment_terms_days} ÷ {longest_terms} days"
                              if longest_terms > 0 else f"{weights['payment_terms']} (no quote offers credit)"),
            # An unassessed supplier gets no risk points: unknown is not the same as safe.
            "supplier_risk": (Decimal(weights["supplier_risk"]) * (100 - row.risk_score) / 100
                              if row.risk_score is not None else ZERO,
                              f"{weights['supplier_risk']} × (100 − {row.risk_score}) ÷ 100"
                              if row.risk_score is not None else "0 (supplier risk not assessed)"),
        }
        row.points = {name: _money(value) for name, (value, _) in parts.items()}
        row.arithmetic = {name: f"{text} = {row.points[name]}" for name, (_, text) in parts.items()}
        row.score = sum(row.points.values(), ZERO)
    # Ties go to the lower landed cost, then to the name, so the order never depends on input order.
    scored.sort(key=lambda r: (-r.score, r.landed_cost, r.supplier_name))
    return scored + sorted((r for r in rows if r.landed_cost is None), key=lambda r: r.supplier_name)
