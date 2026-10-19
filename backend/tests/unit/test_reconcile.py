"""Bank reconciliation rules (BUILD_PLAN v2.4 change 32; PROMPTS Step 26). Pure function, Decimal money."""

from datetime import date
from decimal import Decimal

from app.modules.bank.reconcile import BankIn, PaymentIn, reconcile

D = Decimal


def bank(n, ref, amount, day=date(2026, 10, 19), narration="NEFT/SHREEJI OFFICE SUPPLIES/SOS-0201"):
    return BankIn(id=f"b{n}", txn_date=day, narration=narration, reference=ref, debit=D(amount))


def pay(n, utr, net, day=date(2026, 10, 19), vendor="Shreeji Office Supplies Pvt Ltd"):
    return PaymentIn(id=f"p{n}", utr=utr, net=D(net), paid_on=day, vendor=vendor)


def test_an_exact_utr_matches_whatever_the_narration():
    result = reconcile([bank(1, "SIMN261019ABC", "53940.00", narration="anything")], [pay(1, "SIMN261019ABC", "53940.00")])
    assert result == {"b1": ("p1", "matched", "utr")}


def test_a_utr_inside_the_narration_also_matches():
    result = reconcile([bank(1, "", "53940.00", narration="NEFT SIMN261019ABC SHREEJI")], [pay(1, "SIMN261019ABC", "53940.00")])
    assert result["b1"] == ("p1", "matched", "utr")


def test_amount_date_and_name_only_suggest():
    result = reconcile([bank(1, "BANKREF1", "53940.00", day=date(2026, 10, 21))], [pay(1, None, "53940.00")])
    assert result["b1"] == ("p1", "suggested", "amount_date_name")


def test_no_suggestion_when_the_amount_date_or_name_differs():
    assert reconcile([bank(1, "X", "53940.01")], [pay(1, None, "53940.00")]) == {}
    assert reconcile([bank(1, "X", "53940.00", day=date(2026, 10, 25))], [pay(1, None, "53940.00")]) == {}
    assert reconcile([bank(1, "X", "53940.00", narration="NEFT/OTHER CO")], [pay(1, None, "53940.00")]) == {}


def test_each_payment_is_used_once():
    lines = [bank(1, "SIMN1", "100.00"), bank(2, "SIMN1", "100.00")]
    result = reconcile(lines, [pay(1, "SIMN1", "100.00")])
    assert list(result.values()) == [("p1", "matched", "utr")]


def test_credits_are_ignored():
    credit = BankIn(id="b1", txn_date=date(2026, 10, 19), narration="refund", reference="SIMN1", debit=D("0"))
    assert reconcile([credit], [pay(1, "SIMN1", "100.00")]) == {}
