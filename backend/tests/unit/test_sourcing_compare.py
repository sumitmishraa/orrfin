"""Quote comparison (BUILD_PLAN §6f): landed cost, conversion, disclosed scoring. Pure: no database."""

from decimal import Decimal

import pytest

from app.modules.sourcing.compare import DEFAULT_WEIGHTS, QuoteIn, QuoteLineIn, compare, weight_problems

D = Decimal


def quote(id: str, rate: str, *, freight="0", terms=30, delivery=10, risk: int | None = 0, currency="INR",
          fx: str | None = None, qty="10", tax="18") -> QuoteIn:
    return QuoteIn(id=id, supplier_name=f"Supplier {id}", currency=currency,
                   lines=[QuoteLineIn(D(qty), D(rate), D(tax))], freight=D(freight), payment_terms_days=terms,
                   delivery_days=delivery, risk_score=risk, fx_rate=D(fx) if fx else None)


def test_landed_cost_is_lines_plus_tax_plus_freight():
    (row,) = compare([quote("A", "1000.00", freight="500.00")], "INR", DEFAULT_WEIGHTS)
    assert (row.subtotal, row.tax, row.freight, row.landed_cost) == (D("10000.00"), D("1800.00"), D("500.00"), D("12300.00"))
    assert row.converted is False


def test_tax_is_rounded_per_line_half_up():
    q = QuoteIn(id="A", supplier_name="A", currency="INR", freight=D("0"), payment_terms_days=0, delivery_days=1,
                lines=[QuoteLineIn(D("1"), D("0.25"), D("18")), QuoteLineIn(D("1"), D("0.25"), D("18"))])
    (row,) = compare([q], "INR", DEFAULT_WEIGHTS)
    assert row.tax == D("0.10")  # 0.045 → 0.05 on each line, not 0.09 on the sum


def test_the_best_on_every_measure_scores_100_and_the_arithmetic_is_shown():
    best, other = compare([quote("B", "1250.00", terms=15, delivery=20, risk=50), quote("A", "1000.00")],
                          "INR", DEFAULT_WEIGHTS)
    assert (best.quote_id, best.score) == ("A", D("100.00"))
    assert other.points == {"price": D("48.00"), "delivery": D("10.00"), "payment_terms": D("5.00"),
                            "supplier_risk": D("5.00")}
    assert other.score == D("68.00")
    assert other.arithmetic["price"] == "60 × 11,800.00 ÷ 14,750.00 = 48.00"


def test_the_weights_decide_the_ranking():
    cheap_slow, dear_fast = quote("A", "1000.00", delivery=30), quote("B", "1400.00", delivery=5)
    assert compare([cheap_slow, dear_fast], "INR", DEFAULT_WEIGHTS)[0].quote_id == "A"
    speed_first = {"price": 20, "delivery": 60, "payment_terms": 10, "supplier_risk": 10}
    assert compare([cheap_slow, dear_fast], "INR", speed_first)[0].quote_id == "B"


def test_a_foreign_quote_is_converted_at_the_entered_rate_and_marked():
    (row,) = compare([quote("A", "100.00", currency="AED", fx="22.635", tax="5")], "INR", DEFAULT_WEIGHTS)
    assert row.converted is True and row.landed_cost == D("23766.75")  # (1000 + 50) × 22.635
    assert "Converted from AED" in row.note


def test_a_foreign_quote_with_no_rate_is_shown_but_never_scored_or_estimated():
    rows = compare([quote("A", "100.00", currency="AED"), quote("B", "5000.00")], "INR", DEFAULT_WEIGHTS)
    assert [r.quote_id for r in rows] == ["B", "A"]
    assert rows[1].landed_cost is None and rows[1].score is None and "not scored" in rows[1].note
    assert rows[0].score == D("100.00")  # the unscored quote does not set the lowest price


def test_an_unassessed_supplier_gets_no_risk_points():
    (row,) = compare([quote("A", "1000.00", risk=None)], "INR", DEFAULT_WEIGHTS)
    assert row.points["supplier_risk"] == D("0.00") and row.score == D("90.00")


def test_edge_cases_do_not_divide_by_zero():
    rows = compare([quote("A", "1000.00", terms=0, delivery=0), quote("B", "1000.00", terms=0, delivery=0)],
                   "INR", DEFAULT_WEIGHTS)
    assert [r.score for r in rows] == [D("100.00"), D("100.00")]
    assert [r.quote_id for r in rows] == ["A", "B"]  # a full tie is ordered by name, not by input order
    assert compare([], "INR", DEFAULT_WEIGHTS) == []


@pytest.mark.parametrize("weights", [
    {"price": 60, "delivery": 20, "payment_terms": 10, "supplier_risk": 20},     # adds up to 110
    {"price": 100, "delivery": 0, "payment_terms": 0},                           # one missing
    {"price": 110, "delivery": -10, "payment_terms": 0, "supplier_risk": 0},     # a negative weight
    {"price": 60.0, "delivery": 20, "payment_terms": 10, "supplier_risk": 10},   # a float
    {"price": 60, "delivery": 20, "payment_terms": 10, "supplier_risk": 10, "friendship": 0},
])
def test_bad_weights_are_refused(weights):
    assert weight_problems(weights)
    with pytest.raises(ValueError):
        compare([quote("A", "1000.00")], "INR", weights)
