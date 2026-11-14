"""Contracts: upload, proposed terms, human confirmation, activation, obligations (BUILD_PLAN change 44).

draft (file uploaded, terms proposed and confirmed by a person) → active → expired | terminated.
- AI or the pattern reader only proposes terms; a person confirms or corrects each one, and the
  term then records who did. A contract cannot be activated while any term is unconfirmed.
- Playbook flags are fixed rules over the confirmed terms (auto-renewal, short notice, no
  liability cap, short payment terms). They warn; they never block or approve.
- Activating with an end date and a notice period adds a "decide on renewal" obligation due
  before the notice deadline, assigned to the contract owner.
"""

import hashlib
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import (
    TERM_FIELDS, Contract, ContractObligation, ContractTerm, Document, Supplier, User, Vendor,
)
from app.modules.audit.service import record_event
from app.modules.contracts.reader import propose_terms
from app.modules.invoices.providers import get_file_store
from app.modules.notifications.service import notify

VIEW_ROLES = ("buyer", "approver", "finance", "admin")
EDIT_ROLES = ("buyer", "finance", "admin")


def audit(db: Session, contract: Contract, actor_id: uuid.UUID | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=contract.org_id, entity_type="contract", entity_id=contract.id, actor_id=actor_id,
                 action=action, payload={"status": contract.status, **(payload or {})})


def load(db: Session, user: User, contract_id: uuid.UUID, *, lock: bool = False) -> Contract:
    if user.role not in VIEW_ROLES:
        raise NotFound("Contract not found.")
    query = select(Contract).where(Contract.id == contract_id, Contract.org_id == user.org_id)
    contract = db.scalar(query.with_for_update() if lock else query)
    if contract is None:
        raise NotFound("Contract not found.")
    return contract


def _editor(user: User) -> None:
    if user.role not in EDIT_ROLES:
        raise Forbidden("Only a buyer, finance or an admin can change contracts.")


def create(db: Session, user: User, *, title: str, supplier_id: uuid.UUID | None, vendor_id: uuid.UUID | None) -> Contract:
    _editor(user)
    if not title.strip():
        raise Invalid("Give the contract a title.")
    for model, value in ((Supplier, supplier_id), (Vendor, vendor_id)):
        if value is not None and db.scalar(select(model.id).where(model.id == value, model.org_id == user.org_id)) is None:
            raise NotFound("That supplier was not found.")
    contract = Contract(id=uuid.uuid4(), org_id=user.org_id, title=title.strip()[:200], supplier_id=supplier_id,
                        vendor_id=vendor_id, owner_id=user.id, status="draft")
    db.add(contract)
    db.flush()
    audit(db, contract, user.id, "created", {"title": contract.title})
    return contract


def terms_of(db: Session, contract: Contract) -> dict[str, ContractTerm]:
    return {t.field: t for t in db.scalars(select(ContractTerm).where(ContractTerm.contract_id == contract.id))}


def upload(db: Session, user: User, contract_id: uuid.UUID, *, filename: str, data: bytes) -> dict[str, Any]:
    """Store the signed PDF and replace any unconfirmed proposals with new ones. Confirmed terms are kept."""
    _editor(user)
    contract = load(db, user, contract_id, lock=True)
    if contract.status != "draft":
        raise Conflict("Only a draft contract takes a new file.")
    if len(data) > get_settings().max_upload_bytes or not data.startswith(b"%PDF-"):
        raise Invalid("Upload the signed contract as a PDF of up to 10 MB.")
    sha256 = hashlib.sha256(data).hexdigest()
    document = db.scalar(select(Document).where(Document.org_id == user.org_id, Document.sha256 == sha256))
    if document is None:
        key = f"{user.org_id}/contracts/{sha256}.pdf"
        get_file_store().put(key, data)
        document = Document(org_id=user.org_id, s3_key=key, sha256=sha256, filename=(filename or "contract.pdf")[:255],
                            content_type="application/pdf", size_bytes=len(data), uploaded_by=user.id)
        db.add(document)
        db.flush()
    contract.document_id = document.id
    proposals, model_id = propose_terms(data)
    existing = terms_of(db, contract)
    added = []
    for proposal in proposals:
        current = existing.get(proposal["field"])
        if current is not None and current.confirmed_by is not None:
            continue  # never overwrite what a person confirmed
        if current is not None:
            db.delete(current)
            db.flush()
        db.add(ContractTerm(org_id=user.org_id, contract_id=contract.id, field=proposal["field"],
                            value=proposal["value"], evidence={**proposal["evidence"], "model_id": model_id}, source="ai"))
        added.append(proposal["field"])
    db.flush()
    audit(db, contract, user.id, "file_uploaded", {"sha256": sha256, "proposed": added, "model_id": model_id})
    return {"proposed": added, "model_id": model_id}


def set_term(db: Session, user: User, contract_id: uuid.UUID, field: str, value: str) -> ContractTerm:
    """A person enters, corrects or confirms one term. Whatever they save counts as confirmed by them."""
    _editor(user)
    contract = load(db, user, contract_id, lock=True)
    if contract.status != "draft":
        raise Conflict("The terms of an active contract are fixed.")
    if field not in TERM_FIELDS:
        raise Invalid(f"Unknown term. Use one of: {', '.join(TERM_FIELDS)}.")
    value = value.strip()
    if not value:
        raise Invalid("Enter a value.")
    if field in ("start_date", "end_date"):
        try:
            value = date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise Invalid("Use a date in the form YYYY-MM-DD.") from exc
    if field == "notice_days" and (not value.isdigit() or int(value) > 3650):
        raise Invalid("Notice is a whole number of days.")
    term = terms_of(db, contract).get(field)
    old = term.value if term else None
    if term is None:
        term = ContractTerm(org_id=user.org_id, contract_id=contract.id, field=field, value=value, source="human")
        db.add(term)
    term.value, term.confirmed_by = value[:500], user.id
    db.flush()
    audit(db, contract, user.id, "term_confirmed", {"field": field, "old": old, "new": term.value,
                                                     "proposed_by_ai": term.source == "ai"})
    return term


def flags(terms: dict[str, str]) -> list[str]:
    """Playbook warnings over confirmed terms. Fixed rules; they never decide anything."""
    out = []
    if "renewal" in terms and "auto" in terms["renewal"].casefold():
        out.append("The contract renews automatically: diarise the notice date.")
    if terms.get("notice_days", "").isdigit() and int(terms["notice_days"]) < 30:
        out.append("The notice period is shorter than 30 days.")
    if "liability_cap" not in terms:
        out.append("No liability cap is recorded.")
    if "end_date" not in terms:
        out.append("No end date is recorded, so no renewal reminder can be set.")
    return out


def activate(db: Session, user: User, contract_id: uuid.UUID) -> Contract:
    _editor(user)
    contract = load(db, user, contract_id, lock=True)
    if contract.status != "draft":
        raise Conflict("Only a draft contract can be activated.")
    if contract.document_id is None:
        raise Invalid("Upload the signed contract first.")
    terms = terms_of(db, contract)
    unconfirmed = sorted(f for f, t in terms.items() if t.confirmed_by is None)
    if unconfirmed:
        raise Conflict("Confirm or correct these proposed terms first: " + ", ".join(unconfirmed) + ".")
    contract.status, contract.activated_by = "active", user.id
    values = {f: t.value for f, t in terms.items()}
    if "end_date" in values:
        end = date.fromisoformat(values["end_date"])
        notice = int(values.get("notice_days", "0") or 0)
        due = end - timedelta(days=notice + 14)  # two weeks before the notice deadline, to leave time to act
        db.add(ContractObligation(org_id=user.org_id, contract_id=contract.id, owner_id=contract.owner_id,
                                  description=f"Decide whether to renew “{contract.title}” (notice: {notice} days)",
                                  due_on=max(due, date.today()), kind="renewal_notice"))
    db.flush()
    audit(db, contract, user.id, "activated", {"terms": values, "flags": flags(values)})
    return contract


def add_obligation(db: Session, user: User, contract_id: uuid.UUID, *, description: str, due_on: date,
                   owner_id: uuid.UUID) -> ContractObligation:
    _editor(user)
    contract = load(db, user, contract_id, lock=True)
    if db.scalar(select(User.id).where(User.id == owner_id, User.org_id == user.org_id, User.active)) is None:
        raise NotFound("That person was not found.")
    if not description.strip():
        raise Invalid("Describe the obligation.")
    row = ContractObligation(org_id=user.org_id, contract_id=contract.id, description=description.strip()[:300],
                             due_on=due_on, owner_id=owner_id)
    db.add(row)
    db.flush()
    audit(db, contract, user.id, "obligation_added", {"description": row.description, "due_on": due_on.isoformat()})
    notify(db, org_id=user.org_id, user_id=owner_id, kind="contract_obligation",
           title=f"New obligation on {contract.title}", body=row.description, link=f"/contracts/{contract.id}")
    return row


def complete_obligation(db: Session, user: User, contract_id: uuid.UUID, obligation_id: uuid.UUID) -> ContractObligation:
    contract = load(db, user, contract_id, lock=True)
    row = db.scalar(select(ContractObligation).where(ContractObligation.id == obligation_id,
                                                     ContractObligation.contract_id == contract.id))
    if row is None:
        raise NotFound("Obligation not found.")
    if user.id not in (row.owner_id, contract.owner_id) and user.role != "admin":
        raise Forbidden("Only the obligation's owner, the contract owner or an admin can mark it done.")
    if row.status != "done":
        row.status = "done"
        audit(db, contract, user.id, "obligation_done", {"obligation_id": row.id})
    return row


def detail(db: Session, contract: Contract) -> dict[str, Any]:
    terms = terms_of(db, contract)
    confirmed = {f: t.value for f, t in terms.items() if t.confirmed_by}
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == contract.org_id)).all())
    return {
        "id": contract.id, "title": contract.title, "status": contract.status, "supplier_id": contract.supplier_id,
        "vendor_id": contract.vendor_id, "owner_name": names.get(contract.owner_id), "has_file": contract.document_id is not None,
        "terms": [{"field": f, "value": t.value, "source": t.source, "evidence": t.evidence,
                   "confirmed_by": names.get(t.confirmed_by)} for f, t in sorted(terms.items())],
        "flags": flags(confirmed) if contract.status == "active" or confirmed else [],
        "obligations": [{"id": o.id, "description": o.description, "due_on": o.due_on, "status": o.status,
                         "kind": o.kind, "owner_name": names.get(o.owner_id)}
                        for o in db.scalars(select(ContractObligation).where(ContractObligation.contract_id == contract.id)
                                            .order_by(ContractObligation.due_on))],
    }


def list_contracts(db: Session, user: User) -> list[dict[str, Any]]:
    if user.role not in VIEW_ROLES:
        raise Forbidden("Your role cannot see contracts.")
    out = []
    for c in db.scalars(select(Contract).where(Contract.org_id == user.org_id).order_by(Contract.updated_at.desc())):
        end = db.scalar(select(ContractTerm.value).where(ContractTerm.contract_id == c.id, ContractTerm.field == "end_date",
                                                         ContractTerm.confirmed_by.is_not(None)))
        out.append({"id": c.id, "title": c.title, "status": c.status, "end_date": end})
    return out
