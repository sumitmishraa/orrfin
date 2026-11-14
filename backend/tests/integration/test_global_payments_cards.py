"""Global payments and vendor cards, both simulated (BUILD_PLAN changes 45-46, ADR 0008, §11 M12).

What must hold: IBAN/SWIFT/IFSC are checked; a run pays in one currency and never converts an
invoice; the mock bank refuses a payee whose details do not suit the currency; the payment advice
is a real PDF that says "simulated"; a card cannot outspend its request, its lock or its state,
cannot be issued by the requester, and is invisible to other people and orgs.
"""

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.jobs import drain
from app.modules.payments.banking import iban_ok, ifsc_ok, swift_matches_iban, swift_ok
from tests.conftest import login
from tests.integration.test_payments import _profile, _run_with_invoice, _verified, pay  # noqa: F401  (fixture)
from tests.integration.test_invoice_review import team  # noqa: F401  (fixture)
from tests.integration.test_procurement import _complete_and_send, _decide, _new_request, world  # noqa: F401

UAE_IBAN = "AE070331234567890123456"


@pytest.mark.parametrize("value, ok", [(UAE_IBAN, True), ("AE07 0331 2345 6789 0123 456", True),
                                       ("AE080331234567890123456", False), ("AE07033123456789012345", False),
                                       ("US070331234567890123456", False), ("", False)])
def test_iban_check_digits_length_and_country(value, ok):
    assert iban_ok(value) is ok


def test_swift_and_ifsc_formats():
    assert swift_ok("EBILAEAD") and swift_ok("EBILAEADXXX") and not swift_ok("EBIL1EAD") and not swift_ok("EBILAEA")
    assert swift_matches_iban("EBILAEAD", UAE_IBAN) and not swift_matches_iban("HDFCINBB", UAE_IBAN)
    assert ifsc_ok("HDFC0001234") and not ifsc_ok("HDFC1001234")


def test_international_payee_details_are_checked(client, pay):
    intl = {"ifsc": None, "bank_account": UAE_IBAN, "swift_bic": "EBILAEAD"}
    assert _profile(client, pay.payer, pay.vendor_id, **intl).status_code == 200
    for bad in ({"bank_account": "AE080331234567890123456"}, {"swift_bic": "HDFCINBB"},
                {"ifsc": "HDFC0001234"}, {"swift_bic": "XX"}):
        assert _profile(client, pay.payer, pay.vendor_id, **{**intl, **bad}).status_code == 422, bad


def test_a_run_pays_in_one_currency_and_never_converts(client, pay):
    login(client, pay.payer)
    assert client.post("/payment-runs", json={"currency": "GBP"}).status_code == 422
    aed = client.post("/payment-runs", json={"currency": "AED"}).json()
    assert aed["currency"] == "AED"
    refused = client.post(f"/payment-runs/{aed['id']}/invoices", json={"invoice_id": pay.invoice_id})
    assert refused.status_code == 409 and "INR" in refused.json()["detail"]


def _settle(client, db, pay) -> dict:
    run = _run_with_invoice(client, pay)
    client.post(f"/payment-runs/{run['id']}/submit")
    login(client, pay.admin)
    assert client.post(f"/payment-runs/{run['id']}/approve", json={"reason": "Checked with the vendor."}).status_code == 200
    client.post(f"/payment-runs/{run['id']}/send")
    drain(db)
    return client.get(f"/payment-runs/{run['id']}").json()


def test_the_payment_advice_is_a_pdf_that_says_simulated(client, db, pay):
    _verified(client, pay)
    run_before = _run_with_invoice(client, pay)
    assert client.get(f"/payment-runs/{run_before['id']}/advice").status_code == 409   # not settled yet
    client.post(f"/payment-runs/{run_before['id']}/cancel")
    settled = _settle(client, db, pay)
    advice = client.get(f"/payment-runs/{settled['id']}/advice")
    assert advice.status_code == 200 and advice.headers["content-type"] == "application/pdf"
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(advice.content)).pages)
    squashed = "".join(text.split())  # narrow table cells wrap long references onto two lines
    assert "Simulatedpayment" in squashed and settled["lines"][0]["utr"] in squashed and "53,940.00" in squashed


def test_the_mock_bank_refuses_a_payee_whose_details_do_not_suit_the_currency(client, db, pay):
    _verified(client, pay, ifsc=None, bank_account=UAE_IBAN, swift_bic="EBILAEAD")
    settled = _settle(client, db, pay)
    assert settled["status"] == "partly_failed"
    assert "do not suit a payment in this currency" in settled["lines"][0]["failure_reason"]


# --- Vendor cards ------------------------------------------------------------------------------------

def _approved_request(client, world) -> dict:
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    assert _decide(client, world.manager, request["id"], 1).json()["status"] == "approved"
    return request


def _issue(client, user, request_id, limit="10000.00", **extra):
    login(client, user)
    return client.post("/cards", json={"request_id": request_id, "limit": limit, **extra})


def test_a_card_spends_only_within_its_request_lock_and_state(client, world):
    draft = _new_request(client, world, amount="40000.00")
    assert _issue(client, world.finance, draft["id"]).status_code == 409                # not approved yet
    request = _approved_request(client, world)
    assert _issue(client, world.requester, request["id"]).status_code == 403            # a requester never issues
    assert _issue(client, world.finance, request["id"], limit="40000.01").status_code == 422
    card = _issue(client, world.finance, request["id"], merchant_lock="Office Mart").json()
    assert card["notice"].startswith("Simulated") and len(card["last4"]) == 4 and "number" not in card
    assert _issue(client, world.finance, request["id"], limit="30000.01").status_code == 422  # both cards > request

    def charge(user, merchant, amount):
        login(client, user)
        return client.post(f"/cards/{card['id']}/simulate-charge", json={"merchant": merchant, "amount": amount}).json()

    after = charge(world.requester, "Office Mart", "6000.00")
    assert after["spent"] == "6000.00" and after["transactions"][-1]["status"] == "approved"
    assert charge(world.requester, "Gadget World", "10.00")["transactions"][-1]["decline_reason"].startswith("The card only works")
    over = charge(world.requester, "office mart", "4000.01")
    assert over["transactions"][-1]["status"] == "declined" and over["spent"] == "6000.00"

    login(client, world.requester)
    assert client.put(f"/cards/{card['id']}/status", json={"status": "frozen"}).json()["status"] == "frozen"
    assert client.put(f"/cards/{card['id']}/status", json={"status": "active"}).status_code == 403
    assert charge(world.requester, "Office Mart", "1.00")["transactions"][-1]["decline_reason"] == "The card is frozen."
    login(client, world.finance)
    assert client.put(f"/cards/{card['id']}/status", json={"status": "closed"}).json()["status"] == "closed"
    assert client.put(f"/cards/{card['id']}/status", json={"status": "active"}).status_code == 409


def test_cards_are_seen_by_their_holder_and_finance_only(client, factory, world):
    request = _approved_request(client, world)
    card = _issue(client, world.finance, request["id"]).json()
    login(client, world.buyer)
    assert client.get("/cards").json() == [] and client.get(f"/cards/{card['id']}").status_code == 404
    other = factory.user(factory.org("Other org"), "admin")
    login(client, other)
    assert client.get(f"/cards/{card['id']}").status_code == 404
    assert client.post(f"/cards/{card['id']}/simulate-charge", json={"merchant": "X", "amount": "1.00"}).status_code == 404
    assert _issue(client, other, request["id"]).status_code == 404
    login(client, world.requester)
    assert [c["id"] for c in client.get("/cards").json()] == [card["id"]]
    assert Decimal(client.get(f"/cards/{card['id']}").json()["available"]) == Decimal("10000.00")
