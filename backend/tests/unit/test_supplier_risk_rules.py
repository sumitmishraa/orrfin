"""Supplier-risk rules (BUILD_PLAN §6e): every block and hold has a test; the score is plain arithmetic."""

from datetime import date, timedelta

import pytest

from app.modules.supplier_risk.rules import (
    WEIGHTS,
    DocumentFact,
    SupplierFacts,
    assess,
    level_for,
    normalise_name,
)

TODAY = date(2026, 11, 14)
ALL_NO = {"data_security_policy": "yes", "related_party": "no", "legal_proceedings": "no"}


def clean_supplier(**changes) -> SupplierFacts:
    """An Indian goods supplier with nothing wrong."""
    facts = SupplierFacts(
        legal_name="Zenith Trading Pvt Ltd", country="IN", tax_id="27AAACZ1234F1Z5", category="goods", today=TODAY,
        documents=[DocumentFact("tax_certificate"), DocumentFact("pan"), DocumentFact("bank_proof")],
        answers=dict(ALL_NO), bank_fingerprint="fp-zenith", other_bank_fingerprints=frozenset({"fp-other"}),
        sanctioned_names=("Blocked Exports LLC",))
    for name, value in changes.items():
        setattr(facts, name, value)
    return facts


def codes(outcome, kind: str) -> list[str]:
    return sorted(f.code for f in outcome.findings if f.kind == kind)


def test_a_clean_supplier_has_no_findings_and_a_low_score():
    outcome = assess(clean_supplier())
    assert outcome.blocks == [] and outcome.holds == []
    assert (outcome.score, outcome.level) == (0, "low")
    assert [f.rule for f in outcome.findings] == ["tax_id", "sanctions", "documents", "bank", "questionnaire"]


def test_a_clean_uae_supplier_needs_a_trn_and_no_pan():
    outcome = assess(clean_supplier(country="AE", tax_id="100234567800003",
                                    documents=[DocumentFact("tax_certificate"), DocumentFact("bank_proof")]))
    assert outcome.blocks == [] and outcome.holds == []


# --- Blocks ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("country, tax_id", [("IN", "100234567800003"), ("AE", "27AAACZ1234F1Z5"),
                                             ("IN", ""), ("AE", "10023456780000")])
def test_a_badly_formed_tax_number_blocks(country, tax_id):
    assert "TAX_ID_INVALID" in codes(assess(clean_supplier(country=country, tax_id=tax_id)), "block")


@pytest.mark.parametrize("name", ["Blocked Exports LLC", "BLOCKED EXPORTS L.L.C.", "  blocked   exports "])
def test_a_name_on_the_sanctions_list_blocks_however_it_is_written(name):
    outcome = assess(clean_supplier(legal_name=name))
    assert codes(outcome, "block") == ["SANCTIONS_MATCH"] and outcome.level == "critical"


def test_a_similar_but_different_name_is_not_a_match():
    assert assess(clean_supplier(legal_name="Blocked Exports Trading")).blocks == []
    assert normalise_name("Zenith Trading Pvt. Ltd.") == normalise_name("ZENITH TRADING PRIVATE LIMITED")


def test_a_missing_required_document_blocks():
    outcome = assess(clean_supplier(documents=[DocumentFact("bank_proof")]))
    assert codes(outcome, "block") == ["DOCUMENT_MISSING", "DOCUMENT_MISSING"]  # tax certificate and PAN


def test_an_expired_document_blocks_unless_a_current_copy_is_on_file():
    yesterday = TODAY - timedelta(days=1)
    expired = [DocumentFact("tax_certificate", yesterday), DocumentFact("pan"), DocumentFact("bank_proof")]
    assert codes(assess(clean_supplier(documents=expired)), "block") == ["DOCUMENT_EXPIRED"]
    renewed = [*expired, DocumentFact("tax_certificate", TODAY + timedelta(days=400))]
    assert assess(clean_supplier(documents=renewed)).blocks == []


def test_a_bank_account_shared_with_another_supplier_blocks():
    outcome = assess(clean_supplier(other_bank_fingerprints=frozenset({"fp-zenith"})))
    assert codes(outcome, "block") == ["BANK_SHARED"]


# --- Holds ----------------------------------------------------------------------------------------

def test_no_bank_proof_holds():
    outcome = assess(clean_supplier(documents=[DocumentFact("tax_certificate"), DocumentFact("pan")]))
    assert outcome.blocks == [] and codes(outcome, "hold") == ["NO_BANK_PROOF"]


def test_bank_details_changed_in_the_last_30_days_hold():
    recent = assess(clean_supplier(bank_changed_on=TODAY - timedelta(days=30)))
    assert codes(recent, "hold") == ["BANK_RECENTLY_CHANGED"]
    assert assess(clean_supplier(bank_changed_on=TODAY - timedelta(days=31))).holds == []


def test_a_document_expiring_within_30_days_holds():
    soon = [DocumentFact("tax_certificate", TODAY + timedelta(days=30)), DocumentFact("pan"), DocumentFact("bank_proof")]
    assert codes(assess(clean_supplier(documents=soon)), "hold") == ["DOCUMENT_EXPIRING"]
    later = [DocumentFact("tax_certificate", TODAY + timedelta(days=31)), DocumentFact("pan"), DocumentFact("bank_proof")]
    assert assess(clean_supplier(documents=later)).holds == []


def test_flagged_and_missing_questionnaire_answers_hold():
    software = assess(clean_supplier(category="software", answers={**ALL_NO, "data_security_policy": "no"}))
    assert codes(software, "hold") == ["QUESTIONNAIRE_FLAG"]
    # The same answer from a goods supplier is not a flag.
    assert assess(clean_supplier(answers={**ALL_NO, "data_security_policy": "no"})).holds == []
    related = assess(clean_supplier(answers={**ALL_NO, "related_party": "yes", "legal_proceedings": "yes"}))
    assert codes(related, "hold") == ["QUESTIONNAIRE_FLAG", "QUESTIONNAIRE_FLAG"]
    assert codes(assess(clean_supplier(answers={"related_party": "maybe"})), "hold") == ["QUESTIONNAIRE_INCOMPLETE"]


# --- Score and level ------------------------------------------------------------------------------

def test_the_score_is_the_sum_of_fixed_weights_capped_at_100():
    outcome = assess(clean_supplier(documents=[DocumentFact("tax_certificate"), DocumentFact("pan")],
                                    answers={**ALL_NO, "related_party": "yes"}))
    assert outcome.score == WEIGHTS["NO_BANK_PROOF"] + WEIGHTS["QUESTIONNAIRE_FLAG"] == 35
    assert outcome.level == "medium"
    worst = assess(clean_supplier(legal_name="Blocked Exports LLC", tax_id="bad", documents=[]))
    assert worst.score == 100 and worst.level == "critical"


@pytest.mark.parametrize("score, level", [(0, "low"), (19, "low"), (20, "medium"), (49, "medium"),
                                          (50, "high"), (79, "high"), (80, "critical"), (100, "critical")])
def test_level_bands(score, level):
    assert level_for(score) == level


def test_an_unknown_country_is_refused_not_guessed():
    with pytest.raises(ValueError):
        assess(clean_supplier(country="US"))
