"""Bank identifier checks for payees (BUILD_PLAN change 45). Pure functions, no network.

These catch typing mistakes before money is (simulated to be) sent. They do not prove an account
belongs to the payee: that is what the maker-checker verification of bank details is for.
"""

import re

IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
INDIAN_ACCOUNT = re.compile(r"^[0-9]{9,18}$")
# ISO 9362: 4 letters bank, 2 letters country, 2 letters/digits location, optional 3 branch.
SWIFT_BIC = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
# Lengths for the countries Orrfin pays into today; any other country is refused rather than guessed.
IBAN_LENGTHS = {"AE": 23, "GB": 22, "DE": 22, "FR": 27, "NL": 18, "SA": 24}


def clean(value: str | None) -> str:
    return re.sub(r"\s", "", value or "").upper()


def ifsc_ok(value: str) -> bool:
    return bool(IFSC.match(clean(value)))


def swift_ok(value: str) -> bool:
    return bool(SWIFT_BIC.match(clean(value)))


def iban_ok(value: str) -> bool:
    """ISO 13616: known country, right length, and the mod-97 check digits add up."""
    iban = clean(value)
    if not IBAN_SHAPE.match(iban) or IBAN_LENGTHS.get(iban[:2]) != len(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def swift_matches_iban(swift: str, iban: str) -> bool:
    """The bank's country in the BIC must be the IBAN's country: a cheap catch for a pasted wrong code."""
    return clean(swift)[4:6] == clean(iban)[:2]
