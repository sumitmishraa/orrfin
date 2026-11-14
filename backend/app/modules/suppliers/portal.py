"""The supplier portal: a separate login realm and what a supplier may do in it (BUILD_PLAN §9 v3.0).

A supplier contact signs in with `supplier_users` and gets its own cookie and session table.
Nothing here accepts an employee session, and no employee route accepts a supplier session, so
the two realms cannot reach each other. Every function takes the signed-in `SupplierUser` and
works on that contact's own supplier only; there is no supplier id in any portal request.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, verify_password
from app.config import get_settings
from app.errors import Conflict, Invalid
from app.models import Supplier, SupplierDocument, SupplierInvite, SupplierSession, SupplierUser
from app.modules.invoices.providers import get_file_store
from app.modules.matching.tax import GSTIN_FORMAT, TRN_FORMAT
from app.modules.notifications.service import notify
from app.modules.supplier_risk import rules
from app.modules.suppliers import service
from app.security.secrets import encrypt_credentials

COOKIE_NAME = "orrfin_supplier"
MIN_PASSWORD = 12
EDITABLE_STATUSES = ("invited", "rejected")
# Same accepted uploads as invoices: the first bytes must really be that type.
UPLOAD_TYPES = {"application/pdf": (b"%PDF-", "pdf"), "image/jpeg": (b"\xff\xd8\xff", "jpg"),
                "image/png": (b"\x89PNG\r\n\x1a\n", "png")}
PAN_FORMAT = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_FORMAT = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_FORMAT = re.compile(r"^[0-9]{9,18}$")
UAE_IBAN_FORMAT = re.compile(r"^AE[0-9]{21}$")
# What a supplier is told about its own file. Sanctions, shared-account and questionnaire flags are
# for the reviewer only: telling the supplier would tip them off.
SHOWN_TO_SUPPLIER = {"TAX_ID_INVALID", "DOCUMENT_MISSING", "DOCUMENT_EXPIRED", "DOCUMENT_EXPIRING",
                     "NO_BANK_PROOF", "QUESTIONNAIRE_INCOMPLETE"}


# --- Sign-up and sign-in ---------------------------------------------------------------------------

def accept_invite(db: Session, token: str, password: str) -> SupplierUser:
    """Use an invitation once to set the contact's password. A used, expired or unknown link is refused alike."""
    if len(password) < MIN_PASSWORD or len(password) > 200:
        raise Invalid(f"Choose a password of at least {MIN_PASSWORD} characters.")
    invite = db.scalar(select(SupplierInvite).where(SupplierInvite.token_hash == service.token_hash(token or ""))
                       .with_for_update())
    if invite is None or invite.used_at is not None or invite.expires_at <= datetime.now(UTC):
        raise Invalid("This invitation link is not valid any more. Ask your contact for a new one.")
    contact = db.get(SupplierUser, invite.supplier_user_id)
    contact.password_hash = hash_password(password)
    invite.used_at = datetime.now(UTC)
    service.audit(db, db.get(Supplier, invite.supplier_id), None, "invite_accepted", {"supplier_user_id": contact.id})
    return contact


def authenticate(db: Session, email: str, password: str) -> SupplierUser | None:
    contact = db.scalar(select(SupplierUser).where(func.lower(SupplierUser.email) == email.strip().lower()))
    # verify_password runs even for an unknown email, so timing does not reveal which contacts exist.
    if not verify_password(contact.password_hash if contact else None, password):
        return None
    return contact if contact is not None and contact.active else None


def start_session(db: Session, contact: SupplierUser) -> str:
    token = secrets.token_urlsafe(32)
    db.add(SupplierSession(org_id=contact.org_id, supplier_user_id=contact.id, token_hash=service.token_hash(token),
                           expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_hours)))
    return token


def contact_for_token(db: Session, token: str | None) -> SupplierUser | None:
    if not token:
        return None
    row = db.execute(select(SupplierUser, SupplierSession.expires_at)
                     .join(SupplierSession, SupplierSession.supplier_user_id == SupplierUser.id)
                     .where(SupplierSession.token_hash == service.token_hash(token))).first()
    if row is None or row[1] <= datetime.now(UTC) or not row[0].active:
        return None
    return row[0]


def end_session(db: Session, token: str) -> None:
    db.execute(delete(SupplierSession).where(SupplierSession.token_hash == service.token_hash(token)))


# --- The supplier's own record ---------------------------------------------------------------------

def my_supplier(db: Session, contact: SupplierUser, *, lock: bool = False) -> Supplier:
    query = select(Supplier).where(Supplier.id == contact.supplier_id, Supplier.org_id == contact.org_id)
    return db.scalar(query.with_for_update() if lock else query)


def view(db: Session, contact: SupplierUser) -> dict[str, Any]:
    supplier = my_supplier(db, contact)
    outcome = service.assess(db, supplier)
    return {
        "contact_name": contact.full_name, "legal_name": supplier.legal_name, "country": supplier.country,
        "category": supplier.category, "status": supplier.status, "tax_id": supplier.tax_id, "pan": supplier.pan,
        "answers": supplier.answers, "questions": rules.QUESTIONS, "bank_last4": supplier.bank_last4,
        "review_reason": supplier.review_reason if supplier.status == "rejected" else None,
        "editable": supplier.status in EDITABLE_STATUSES,
        "documents": [{"id": d.id, "kind": d.kind, "filename": d.filename, "expires_on": d.expires_on}
                      for d in service.documents_of(db, supplier)],
        "to_do": [f.message for f in outcome.findings if f.code in SHOWN_TO_SUPPLIER],
    }


def _editable(db: Session, contact: SupplierUser) -> Supplier:
    supplier = my_supplier(db, contact, lock=True)
    if supplier.status not in EDITABLE_STATUSES:
        raise Conflict("Your details are with the reviewer and cannot be changed now.")
    return supplier


def update_profile(db: Session, contact: SupplierUser, *, tax_id: str, pan: str | None,
                   answers: dict[str, str]) -> Supplier:
    supplier = _editable(db, contact)
    tax_id, pan = tax_id.strip().upper(), (pan or "").strip().upper() or None
    name, pattern = ("GSTIN", GSTIN_FORMAT) if supplier.country == "IN" else ("TRN", TRN_FORMAT)
    if not pattern.match(tax_id):
        raise Invalid(f"Enter a valid {name}.")
    if supplier.country == "IN":
        if pan is None or not PAN_FORMAT.match(pan):
            raise Invalid("Enter the company PAN (10 characters, for example AAACZ1234F).")
    elif pan is not None:
        raise Invalid("A UAE company has no PAN.")
    unknown = set(answers) - set(rules.QUESTIONS)
    if unknown or any(value not in ("yes", "no") for value in answers.values()):
        raise Invalid("Answer each question with yes or no.")
    supplier.tax_id, supplier.pan, supplier.answers = tax_id, pan, dict(answers)
    service.audit(db, supplier, None, "profile_updated", {"supplier_user_id": contact.id, "tax_id": tax_id})
    return supplier


def _iban_checks_out(iban: str) -> bool:
    """ISO 13616 mod-97 check: move the first four characters to the end, letters become numbers."""
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def bank_fingerprint(org_id: uuid.UUID, account: str, routing: str) -> str:
    """A keyed one-way mark of a bank account, to spot two suppliers sharing one without storing the number."""
    key = get_settings().orrfin_secret_key
    secret = key.get_secret_value().encode("utf-8") if key else b"orrfin-local-only"
    return hmac.new(secret, f"{org_id}|{routing}|{account}".encode("utf-8"), hashlib.sha256).hexdigest()


def set_bank(db: Session, contact: SupplierUser, *, account_name: str, account_number: str,
             ifsc: str | None) -> Supplier:
    """Save bank details. Allowed at any time, but a change after review sends the supplier back for review."""
    supplier = my_supplier(db, contact, lock=True)
    account_name = account_name.strip()
    account = re.sub(r"\s", "", account_number).upper()
    routing = (ifsc or "").strip().upper()
    if not account_name:
        raise Invalid("Enter the account holder's name.")
    if supplier.country == "IN":
        if not ACCOUNT_FORMAT.match(account) or not IFSC_FORMAT.match(routing):
            raise Invalid("Enter the account number (9 to 18 digits) and the 11-character IFSC.")
    else:
        if not UAE_IBAN_FORMAT.match(account) or not _iban_checks_out(account):
            raise Invalid("Enter a valid UAE IBAN (AE followed by 21 digits).")
        routing = ""
    fingerprint = bank_fingerprint(supplier.org_id, account, routing)
    if fingerprint == supplier.bank_fingerprint:
        return supplier
    changed = supplier.bank_fingerprint is not None
    supplier.bank_details_encrypted = encrypt_credentials(
        {"account_name": account_name, "account_number": account, "ifsc": routing})
    supplier.bank_last4, supplier.bank_fingerprint = account[-4:], fingerprint
    # Only a replacement counts as "changed" (§6e hold); the first details a supplier gives do not.
    supplier.bank_changed_on = date.today() if changed else None
    if supplier.status not in EDITABLE_STATUSES:
        # Changed bank details are the classic payment fraud, so the record goes back to a reviewer.
        supplier.status, supplier.submitted_at = "submitted", datetime.now(UTC)
        service.record_assessment(db, supplier, service.assess(db, supplier))
        notify(db, org_id=supplier.org_id, user_id=supplier.invited_by, kind="supplier_bank_changed",
               title=f"{supplier.legal_name} changed its bank details", body="The supplier needs a new review.",
               link=f"/suppliers/{supplier.id}")
    service.audit(db, supplier, None, "bank_details_changed" if changed else "bank_details_set",
                  {"supplier_user_id": contact.id, "last4": supplier.bank_last4})
    return supplier


def add_document(db: Session, contact: SupplierUser, *, kind: str, filename: str, content_type: str, data: bytes,
                 expires_on: date | None) -> SupplierDocument:
    supplier = my_supplier(db, contact, lock=True)
    if kind not in rules.DOCUMENT_KINDS:
        raise Invalid("Choose what kind of document this is.")
    if len(data) > get_settings().max_upload_bytes:
        raise Invalid("The file is larger than 10 MB.")
    magic, extension = UPLOAD_TYPES.get(content_type, (None, None))
    if magic is None or not data.startswith(magic):
        raise Invalid("Upload a PDF, or a JPEG/PNG scan.")
    sha256 = hashlib.sha256(data).hexdigest()
    # The storage key is built here from ids and the hash; the supplier's file name is never part of a path.
    key = f"{supplier.org_id}/suppliers/{supplier.id}/{sha256}.{extension}"
    get_file_store().put(key, data)
    document = SupplierDocument(id=uuid.uuid4(), org_id=supplier.org_id, supplier_id=supplier.id, kind=kind,
                                s3_key=key, sha256=sha256, filename=(filename or "document")[:255],
                                content_type=content_type, size_bytes=len(data), expires_on=expires_on)
    db.add(document)
    db.flush()
    service.audit(db, supplier, None, "document_added",
                  {"supplier_user_id": contact.id, "kind": kind, "sha256": sha256, "bytes": len(data)})
    return document


def submit(db: Session, contact: SupplierUser) -> Supplier:
    supplier = _editable(db, contact)
    if not supplier.tax_id or not supplier.bank_fingerprint:
        raise Invalid("Fill in your tax number and bank details before you submit.")
    supplier.status, supplier.submitted_at = "submitted", datetime.now(UTC)
    supplier.review_reason = None
    assessment = service.record_assessment(db, supplier, service.assess(db, supplier))
    service.audit(db, supplier, None, "submitted", {"supplier_user_id": contact.id, "risk_level": assessment.level,
                                                    "risk_score": assessment.score})
    notify(db, org_id=supplier.org_id, user_id=supplier.invited_by, kind="supplier_submitted",
           title=f"{supplier.legal_name} sent its details", body="Ready for review by finance.",
           link=f"/suppliers/{supplier.id}")
    return supplier
