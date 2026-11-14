"""Supplier-risk rules (BUILD_PLAN §6e). Pure: plain facts in, results out. No database, no AI.

Three kinds of finding:
- a **block** means the supplier cannot be approved until it is fixed;
- a **hold** means a reviewer may approve, but must write a reason;
- the **score** is fixed weights over the findings, and the **level** comes from fixed bands.
  A `critical` level also holds new purchase orders and payments for that supplier.
AI never scores risk and never clears a finding. Change a weight or a band here only, and bump
the version: it is stored with every assessment so an old decision can be re-explained.
To be reviewed by a compliance professional before any real-data pilot (§12).
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.modules.matching.tax import GSTIN_FORMAT, TRN_FORMAT

SUPPLIER_RISK_RULE_SET_VERSION = "2026.11.1"

COUNTRIES = ("IN", "AE")
CATEGORIES = ("goods", "services", "software")
DOCUMENT_KINDS = ("tax_certificate", "pan", "bank_proof", "other")
# What must be on file before approval, by country. Bank proof is a hold, not a block (§6e).
REQUIRED_DOCUMENTS = {"IN": ("tax_certificate", "pan"), "AE": ("tax_certificate",)}
DOCUMENT_NAMES = {"tax_certificate": "tax registration certificate", "pan": "PAN card", "bank_proof": "bank proof"}
SOON = timedelta(days=30)

# The onboarding questionnaire. Every question is answered "yes" or "no".
QUESTIONS = {
    "data_security_policy": "Do you have a written data-security policy?",
    "related_party": "Is any owner or director related to an employee of the buying company?",
    "legal_proceedings": "Are there open legal or regulatory proceedings against the company?",
}

WEIGHTS = {
    "SANCTIONS_MATCH": 100,
    "TAX_ID_INVALID": 40,
    "BANK_SHARED": 40,
    "DOCUMENT_MISSING": 30,
    "DOCUMENT_EXPIRED": 30,
    "BANK_RECENTLY_CHANGED": 20,
    "NO_BANK_PROOF": 20,
    "QUESTIONNAIRE_FLAG": 15,
    "QUESTIONNAIRE_INCOMPLETE": 10,
    "DOCUMENT_EXPIRING": 10,
}
# Lowest score of each level, highest first.
LEVEL_BANDS = ((80, "critical"), (50, "high"), (20, "medium"), (0, "low"))


@dataclass
class DocumentFact:
    kind: str
    expires_on: date | None = None


@dataclass
class SupplierFacts:
    legal_name: str
    country: str
    tax_id: str
    category: str
    today: date
    documents: list[DocumentFact] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    # A one-way fingerprint of the bank account (never the number itself), and every other supplier's.
    bank_fingerprint: str | None = None
    other_bank_fingerprints: frozenset[str] = frozenset()
    # Set only when earlier bank details were replaced; None for the first details a supplier gives.
    bank_changed_on: date | None = None
    sanctioned_names: tuple[str, ...] = ()


@dataclass
class Finding:
    rule: str
    code: str  # "OK" when the rule passed
    kind: str  # "block", "hold" or "pass"
    message: str

    def as_json(self) -> dict[str, str]:
        return {"rule": self.rule, "code": self.code, "kind": self.kind, "message": self.message}


@dataclass
class RiskOutcome:
    findings: list[Finding]
    score: int
    level: str
    rule_set_version: str = SUPPLIER_RISK_RULE_SET_VERSION

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.kind == "block"]

    @property
    def holds(self) -> list[Finding]:
        return [f for f in self.findings if f.kind == "hold"]

    def as_json(self) -> list[dict[str, str]]:
        return [f.as_json() for f in self.findings]


_COMPANY_SUFFIXES = re.compile(r"\b(private|pvt|limited|ltd|llc|llp|fz|fze|fzc|co|company|inc|corp|corporation)\b")


def normalise_name(name: str) -> str:
    """A company name for comparison: lower-case, no punctuation, no legal suffix, single spaces.

    "Zenith Trading Pvt. Ltd." and "ZENITH TRADING PRIVATE LIMITED" are the same name. This is an
    exact comparison after tidying, on purpose: a looser match would be a guess.
    """
    # Dots vanish ("L.L.C." → "llc"); any other punctuation becomes a space.
    text = re.sub(r"[^a-z0-9 ]", " ", name.casefold().replace(".", ""))
    return " ".join(_COMPANY_SUFFIXES.sub(" ", text).split())


def level_for(score: int) -> str:
    return next(level for floor, level in LEVEL_BANDS if score >= floor)


def assess(facts: SupplierFacts) -> RiskOutcome:
    if facts.country not in COUNTRIES:
        # An unknown country must never fall back to another country's checks.
        raise ValueError(f"Unknown supplier country {facts.country!r}; expected one of {COUNTRIES}.")
    findings: list[Finding] = []

    def passed(rule: str, message: str) -> None:
        findings.append(Finding(rule, "OK", "pass", message))

    # Tax number well formed for the country (block).
    tax_id_name, pattern = ("GSTIN", GSTIN_FORMAT) if facts.country == "IN" else ("TRN", TRN_FORMAT)
    if pattern.match(facts.tax_id or ""):
        passed("tax_id", f"The {tax_id_name} is well formed.")
    else:
        findings.append(Finding("tax_id", "TAX_ID_INVALID", "block",
                                f"“{facts.tax_id}” is not a valid {tax_id_name} format."))

    # Name on the sanctions list (block).
    name = normalise_name(facts.legal_name)
    if name and name in {normalise_name(n) for n in facts.sanctioned_names}:
        findings.append(Finding("sanctions", "SANCTIONS_MATCH", "block",
                                f"“{facts.legal_name}” is on the sanctions list."))
    else:
        passed("sanctions", "The name is not on the sanctions list.")

    # Required documents on file and in date (block); expiring soon (hold).
    documents_ok = True
    by_kind: dict[str, list[DocumentFact]] = {}
    for document in facts.documents:
        by_kind.setdefault(document.kind, []).append(document)
    for kind in REQUIRED_DOCUMENTS[facts.country]:
        if kind not in by_kind:
            documents_ok = False
            findings.append(Finding("documents", "DOCUMENT_MISSING", "block",
                                    f"The {DOCUMENT_NAMES[kind]} has not been uploaded."))
    for kind, documents in by_kind.items():
        # The newest copy counts: an old expired copy does not matter once a current one is on file.
        latest = max(documents, key=lambda d: d.expires_on or date.max)
        label = DOCUMENT_NAMES.get(kind, "document")
        if latest.expires_on is not None and latest.expires_on < facts.today:
            documents_ok = False
            findings.append(Finding("documents", "DOCUMENT_EXPIRED", "block",
                                    f"The {label} expired on {latest.expires_on.isoformat()}."))
        elif latest.expires_on is not None and latest.expires_on - facts.today <= SOON:
            documents_ok = False
            findings.append(Finding("documents", "DOCUMENT_EXPIRING", "hold",
                                    f"The {label} expires on {latest.expires_on.isoformat()}."))
    if documents_ok:
        passed("documents", "Every required document is on file and in date.")

    # Bank account (block when shared; hold when new or unproven).
    bank_ok = True
    if facts.bank_fingerprint and facts.bank_fingerprint in facts.other_bank_fingerprints:
        bank_ok = False
        findings.append(Finding("bank", "BANK_SHARED", "block",
                                "Another supplier already uses this bank account."))
    if "bank_proof" not in by_kind:
        bank_ok = False
        findings.append(Finding("bank", "NO_BANK_PROOF", "hold", "No bank proof has been uploaded."))
    if facts.bank_changed_on is not None and facts.today - facts.bank_changed_on <= SOON:
        bank_ok = False
        findings.append(Finding("bank", "BANK_RECENTLY_CHANGED", "hold",
                                f"The bank details were changed on {facts.bank_changed_on.isoformat()}."))
    if bank_ok:
        passed("bank", "The bank account is not shared, is proven and has not just changed.")

    # Questionnaire (hold).
    questionnaire_ok = True
    unanswered = [key for key in QUESTIONS if facts.answers.get(key) not in ("yes", "no")]
    if unanswered:
        questionnaire_ok = False
        findings.append(Finding("questionnaire", "QUESTIONNAIRE_INCOMPLETE", "hold",
                                f"{len(unanswered)} questionnaire question(s) are not answered."))
    flags = []
    if facts.category == "software" and facts.answers.get("data_security_policy") == "no":
        flags.append("A software supplier has no written data-security policy.")
    if facts.answers.get("related_party") == "yes":
        flags.append("An owner or director is related to an employee of the buying company.")
    if facts.answers.get("legal_proceedings") == "yes":
        flags.append("There are open legal or regulatory proceedings.")
    for message in flags:
        questionnaire_ok = False
        findings.append(Finding("questionnaire", "QUESTIONNAIRE_FLAG", "hold", message))
    if questionnaire_ok:
        passed("questionnaire", "No questionnaire answer needs a second look.")

    # Each finding counts once, so two flagged answers weigh more than one.
    score = min(100, sum(WEIGHTS[f.code] for f in findings if f.kind != "pass"))
    return RiskOutcome(findings=findings, score=score, level=level_for(score))
