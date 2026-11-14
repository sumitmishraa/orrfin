"""Supplier onboarding, the employee side: invite, review, hand over to the ERP (BUILD_PLAN change 41, §9).

invited → (the supplier fills the portal and submits) submitted → approved | rejected
approved → handed_over (a person creates the vendor in the ERP) → active (the sync found it).

Rules that hold here, on the server:
- whoever invited a supplier cannot approve it (segregation of duties);
- a supplier with a blocking risk finding cannot be approved; one with a hold needs a written reason;
- Orrfin never creates or edits a vendor in the ERP: handover is a record for a person to act on;
- bank details are stored encrypted and only their last four characters are ever shown.
Every state change writes its audit event in the same transaction.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import (
    RiskAssessment,
    SanctionsEntry,
    Supplier,
    SupplierDocument,
    SupplierInvite,
    SupplierUser,
    User,
    Vendor,
)
from app.modules.audit.service import record_event
from app.modules.notifications.service import notify
from app.modules.supplier_risk import rules

VIEW_ROLES = ("buyer", "approver", "finance", "admin")
INVITER_ROLES = ("buyer", "finance", "admin")
REVIEWER_ROLES = ("finance", "admin")
INVITE_DAYS = 7  # §9: invitation links expire in 7 days
REVIEW_AGAIN_AFTER = timedelta(days=365)


def audit(db: Session, supplier: Supplier, actor_id: uuid.UUID | None, action: str,
          payload: dict[str, Any] | None = None) -> None:
    record_event(db, org_id=supplier.org_id, entity_type="supplier", entity_id=supplier.id, actor_id=actor_id,
                 action=action, payload={"status": supplier.status, **(payload or {})})


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- Invite ---------------------------------------------------------------------------------------

def invite(db: Session, user: User, *, legal_name: str, country: str, category: str, contact_name: str,
           contact_email: str) -> tuple[Supplier, str]:
    """Create the onboarding record and a single-use invitation. Returns the raw token, which is not stored."""
    if user.role not in INVITER_ROLES:
        raise Forbidden("Only a buyer, finance or an admin can invite a supplier.")
    legal_name, contact_name, email = legal_name.strip(), contact_name.strip(), contact_email.strip().lower()
    if not legal_name or not contact_name:
        raise Invalid("Give the supplier's legal name and a contact person.")
    if country not in rules.COUNTRIES or category not in rules.CATEGORIES:
        raise Invalid("Choose the supplier's country and what they supply.")
    if "@" not in email or len(email) > 320:
        raise Invalid("Enter the contact's email address.")
    if db.scalar(select(SupplierUser.id).where(func.lower(SupplierUser.email) == email)) is not None:
        # One portal login per email across the product, like employee emails.
        raise Conflict("A supplier contact with this email has already been invited.")
    supplier = Supplier(id=uuid.uuid4(), org_id=user.org_id, legal_name=legal_name[:200], country=country,
                        category=category, contact_name=contact_name[:200], contact_email=email,
                        invited_by=user.id, status="invited")
    db.add(supplier)
    db.flush()
    contact = SupplierUser(id=uuid.uuid4(), org_id=user.org_id, supplier_id=supplier.id, email=email,
                           full_name=contact_name[:200])
    db.add(contact)
    db.flush()
    token = new_invite(db, supplier, contact)
    audit(db, supplier, user.id, "invited", {"country": country, "category": category})
    return supplier, token


def new_invite(db: Session, supplier: Supplier, contact: SupplierUser) -> str:
    token = secrets.token_urlsafe(32)
    db.add(SupplierInvite(org_id=supplier.org_id, supplier_id=supplier.id, supplier_user_id=contact.id,
                          token_hash=token_hash(token), expires_at=datetime.now(UTC) + timedelta(days=INVITE_DAYS)))
    db.flush()
    return token


# --- Read ------------------------------------------------------------------------------------------

def load_supplier(db: Session, user: User, supplier_id: uuid.UUID, *, lock: bool = False) -> Supplier:
    if user.role not in VIEW_ROLES:
        raise NotFound("Supplier not found.")
    query = select(Supplier).where(Supplier.id == supplier_id, Supplier.org_id == user.org_id)
    supplier = db.scalar(query.with_for_update() if lock else query)
    if supplier is None:
        raise NotFound("Supplier not found.")
    return supplier


def list_suppliers(db: Session, user: User) -> list[Supplier]:
    if user.role not in VIEW_ROLES:
        raise Forbidden("Your role cannot see suppliers.")
    return list(db.scalars(select(Supplier).where(Supplier.org_id == user.org_id)
                           .order_by(Supplier.updated_at.desc())))


def documents_of(db: Session, supplier: Supplier) -> list[SupplierDocument]:
    return list(db.scalars(select(SupplierDocument).where(SupplierDocument.supplier_id == supplier.id)
                           .order_by(SupplierDocument.created_at)))


def assess(db: Session, supplier: Supplier, today: date | None = None) -> rules.RiskOutcome:
    """Run the §6e rules on what is on file right now. Changes nothing."""
    others = db.scalars(select(Supplier.bank_fingerprint).where(
        Supplier.org_id == supplier.org_id, Supplier.id != supplier.id, Supplier.bank_fingerprint.is_not(None)))
    return rules.assess(rules.SupplierFacts(
        legal_name=supplier.legal_name, country=supplier.country, tax_id=supplier.tax_id or "",
        category=supplier.category, today=today or date.today(),
        documents=[rules.DocumentFact(d.kind, d.expires_on) for d in documents_of(db, supplier)],
        answers=dict(supplier.answers or {}), bank_fingerprint=supplier.bank_fingerprint,
        other_bank_fingerprints=frozenset(others), bank_changed_on=supplier.bank_changed_on,
        sanctioned_names=tuple(db.scalars(select(SanctionsEntry.name)))))


def record_assessment(db: Session, supplier: Supplier, outcome: rules.RiskOutcome,
                      reviewed_by: uuid.UUID | None = None) -> RiskAssessment:
    row = RiskAssessment(org_id=supplier.org_id, supplier_id=supplier.id, rule_set_version=outcome.rule_set_version,
                         score=outcome.score, level=outcome.level, results=outcome.as_json(),
                         answers=dict(supplier.answers or {}), reviewed_by=reviewed_by,
                         next_review_on=date.today() + REVIEW_AGAIN_AFTER if reviewed_by else None)
    db.add(row)
    # §6e: a critical level holds new POs and payments until a named reviewer clears it.
    supplier.on_hold = outcome.level == "critical"
    db.flush()
    return row


def summary(supplier: Supplier) -> dict[str, Any]:
    return {"id": supplier.id, "legal_name": supplier.legal_name, "country": supplier.country,
            "category": supplier.category, "status": supplier.status, "contact_name": supplier.contact_name,
            "contact_email": supplier.contact_email, "on_hold": supplier.on_hold, "updated_at": supplier.updated_at}


def detail(db: Session, user: User, supplier: Supplier) -> dict[str, Any]:
    outcome = assess(db, supplier)
    names = dict(db.execute(select(User.id, User.full_name).where(
        User.id.in_({u for u in (supplier.invited_by, supplier.reviewed_by) if u}))).all())
    can_review = user.role in REVIEWER_ROLES and supplier.status == "submitted"
    return {
        **summary(supplier), "tax_id": supplier.tax_id, "pan": supplier.pan, "answers": supplier.answers,
        "questions": rules.QUESTIONS, "bank_last4": supplier.bank_last4, "vendor_id": supplier.vendor_id,
        "invited_by_name": names.get(supplier.invited_by), "reviewed_by_name": names.get(supplier.reviewed_by),
        "review_reason": supplier.review_reason, "submitted_at": supplier.submitted_at,
        "documents": [{"id": d.id, "kind": d.kind, "filename": d.filename, "expires_on": d.expires_on,
                       "uploaded_at": d.created_at} for d in documents_of(db, supplier)],
        "risk": {"score": outcome.score, "level": outcome.level, "rule_set_version": outcome.rule_set_version,
                 "findings": outcome.as_json()},
        "allowed": {
            "decide": can_review and supplier.invited_by != user.id,
            "decide_blocked_reason": "You invited this supplier, so someone else must review it."
            if can_review and supplier.invited_by == user.id else None,
            "handover": user.role in REVIEWER_ROLES and supplier.status == "approved",
        },
    }


# --- Review and handover ---------------------------------------------------------------------------

def decide(db: Session, user: User, supplier_id: uuid.UUID, *, decision: str, reason: str | None) -> Supplier:
    if decision not in ("approve", "reject"):
        raise Invalid("Decision must be approve or reject.")
    if user.role not in REVIEWER_ROLES:
        raise Forbidden("Only finance or an admin can review a supplier.")
    supplier = load_supplier(db, user, supplier_id, lock=True)
    if supplier.status != "submitted":
        raise Conflict("Only a supplier waiting for review can be decided.")
    if supplier.invited_by == user.id:
        raise Forbidden("You invited this supplier, so someone else must review it.")
    reason = (reason or "").strip() or None
    outcome = assess(db, supplier)
    if decision == "reject":
        if not reason:
            raise Invalid("Give a reason when you reject a supplier.")
        supplier.status = "rejected"
    else:
        if outcome.blocks:
            raise Conflict("This supplier cannot be approved yet: " + " ".join(f.message for f in outcome.blocks))
        if outcome.holds and not reason:
            raise Invalid("Write why you approve despite: " + " ".join(f.message for f in outcome.holds))
        # A supplier whose ERP vendor is already linked (a re-review after a change) goes straight back to active.
        supplier.status = "active" if supplier.vendor_id else "approved"
    supplier.reviewed_by, supplier.reviewed_at, supplier.review_reason = user.id, datetime.now(UTC), reason
    assessment = record_assessment(db, supplier, outcome, reviewed_by=user.id)
    audit(db, supplier, user.id, "approved" if decision == "approve" else "rejected",
          {"reason": reason, "risk_score": assessment.score, "risk_level": assessment.level,
           "rule_set_version": assessment.rule_set_version,
           "holds": [f.code for f in outcome.holds], "blocks": [f.code for f in outcome.blocks]})
    notify(db, org_id=supplier.org_id, user_id=supplier.invited_by, kind=f"supplier_{supplier.status}",
           title=f"{supplier.legal_name} was {'approved' if decision == 'approve' else 'rejected'}",
           body=reason or "", link=f"/suppliers/{supplier.id}")
    return supplier


def hand_over(db: Session, user: User, supplier_id: uuid.UUID) -> Supplier:
    """Mark an approved supplier as ready for the ERP. A person creates the vendor there; Orrfin does not."""
    if user.role not in REVIEWER_ROLES:
        raise Forbidden("Only finance or an admin can hand a supplier over to the ERP.")
    supplier = load_supplier(db, user, supplier_id, lock=True)
    if supplier.status != "approved":
        raise Conflict("Only an approved supplier can be handed over.")
    supplier.status = "handed_over"
    audit(db, supplier, user.id, "handed_over", {"tax_id": supplier.tax_id})
    return supplier


def link_synced_vendors(db: Session, org_id: uuid.UUID) -> int:
    """After an ERP sync: a handed-over supplier whose tax number now exists as an ERP vendor becomes active."""
    linked = 0
    waiting = db.scalars(select(Supplier).where(Supplier.org_id == org_id, Supplier.status == "handed_over",
                                                Supplier.tax_id.is_not(None)).with_for_update())
    for supplier in waiting:
        vendors = db.scalars(select(Vendor).where(Vendor.org_id == org_id, Vendor.gstin == supplier.tax_id)).all()
        if len(vendors) != 1:
            continue  # none yet, or two vendors share the number: a person sorts that out in the ERP
        supplier.vendor_id, supplier.status = vendors[0].id, "active"
        audit(db, supplier, None, "linked_to_erp_vendor", {"vendor_id": vendors[0].id, "erp_ref": vendors[0].erp_ref})
        linked += 1
    return linked


def clear_hold(db: Session, user: User, supplier_id: uuid.UUID, reason: str) -> Supplier:
    """A named reviewer lifts the critical-risk hold on POs and payments, with a reason (§6e)."""
    if user.role not in REVIEWER_ROLES:
        raise Forbidden("Only finance or an admin can clear a supplier hold.")
    supplier = load_supplier(db, user, supplier_id, lock=True)
    if not supplier.on_hold:
        raise Conflict("This supplier is not on hold.")
    if supplier.invited_by == user.id:
        raise Forbidden("You invited this supplier, so someone else must clear the hold.")
    if not reason.strip():
        raise Invalid("Give a reason for clearing the hold.")
    supplier.on_hold = False
    audit(db, supplier, user.id, "hold_cleared", {"reason": reason.strip()})
    return supplier


def hold_reason_for_vendor(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID | None) -> str | None:
    """Why new POs and payments to this ERP vendor are held, or None (§6e critical level)."""
    if vendor_id is None:
        return None
    name = db.scalar(select(Supplier.legal_name).where(Supplier.org_id == org_id, Supplier.vendor_id == vendor_id,
                                                       Supplier.on_hold))
    return f"{name} is on a supplier-risk hold. Finance or an admin must clear it first." if name else None
