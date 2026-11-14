"""Vendor cards: issue, spend (simulated), freeze, close (BUILD_PLAN change 46, §9, ADR 0008).

A card exists only for an approved purchase request and can never spend more than that request.
Rules held here:
- finance or an admin issues; whoever raised the request can never issue its card (SoD);
- limit ≤ the request's approved amount, in the request's currency; the card always expires;
- a charge is declined when the card is frozen, closed or expired, the merchant differs from the
  lock, or the charge would pass the limit; every attempt is recorded, approved or not;
- the holder may freeze their card; only finance or an admin unfreezes or closes it;
- a supplier on a risk hold gets no new card.
Every response says the card is simulated. No real card number exists anywhere.
"""

import secrets
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import CardTransaction, PurchaseRequest, User, VendorCard
from app.modules.audit.service import record_event
from app.modules.cards.issuer import get_issuer
from app.modules.suppliers.service import hold_reason_for_vendor

ISSUER_ROLES = ("finance", "admin")
SPENDABLE_REQUESTS = ("approved", "po_drafted", "po_open")
MAX_DAYS = 90
NOTICE = "Simulated card: no real card number exists and no real money can move."


def audit(db: Session, card: VendorCard, actor_id: uuid.UUID | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=card.org_id, entity_type="vendor_card", entity_id=card.id, actor_id=actor_id,
                 action=action, payload={"status": card.status, **(payload or {})})


def as_dict(db: Session, card: VendorCard) -> dict[str, Any]:
    request = db.get(PurchaseRequest, card.request_id)
    return {"id": card.id, "last4": card.last4, "currency": card.currency, "limit": card.limit_amount,
            "spent": card.spent, "available": card.limit_amount - card.spent, "merchant_lock": card.merchant_lock,
            "expires_on": card.expires_on, "status": card.status, "request_id": card.request_id,
            "request_label": f"PR-{request.number:04d}", "notice": NOTICE,
            "transactions": [{"id": t.id, "merchant": t.merchant, "amount": t.amount, "status": t.status,
                              "decline_reason": t.decline_reason, "auth_code": t.auth_code, "at": t.created_at}
                             for t in db.scalars(select(CardTransaction).where(CardTransaction.card_id == card.id)
                                                 .order_by(CardTransaction.created_at))]}


def load(db: Session, user: User, card_id: uuid.UUID, *, lock: bool = False) -> VendorCard:
    query = select(VendorCard).where(VendorCard.id == card_id, VendorCard.org_id == user.org_id)
    card = db.scalar(query.with_for_update() if lock else query)
    if card is None or (user.role not in ISSUER_ROLES and card.holder_id != user.id):
        raise NotFound("Card not found.")
    return card


def list_cards(db: Session, user: User) -> list[VendorCard]:
    query = select(VendorCard).where(VendorCard.org_id == user.org_id).order_by(VendorCard.created_at.desc())
    if user.role not in ISSUER_ROLES:
        query = query.where(VendorCard.holder_id == user.id)
    return list(db.scalars(query))


def issue(db: Session, user: User, *, request_id: uuid.UUID, limit: Decimal, days: int,
          merchant_lock: str | None) -> VendorCard:
    if user.role not in ISSUER_ROLES:
        raise Forbidden("Only finance or an admin can issue a card.")
    request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == request_id,
                                                      PurchaseRequest.org_id == user.org_id).with_for_update())
    if request is None:
        raise NotFound("Request not found.")
    if request.status not in SPENDABLE_REQUESTS:
        raise Conflict("A card can be issued only for an approved request.")
    if request.requested_by == user.id:
        raise Forbidden("You raised this request, so someone else must issue its card.")
    hold = hold_reason_for_vendor(db, user.org_id, request.vendor_id or request.suggested_vendor_id)
    if hold:
        raise Conflict(hold)
    already = sum((c.limit_amount for c in db.scalars(select(VendorCard).where(
        VendorCard.request_id == request.id, VendorCard.status != "closed"))), Decimal("0"))
    if limit <= 0 or already + limit > request.amount:
        raise Invalid(f"The limit must be above 0 and, with other cards on this request, at most {request.amount}.")
    if not 1 <= days <= MAX_DAYS:
        raise Invalid(f"A card lasts 1 to {MAX_DAYS} days.")
    expires_on = date.today() + timedelta(days=days)
    issuer_ref, last4 = get_issuer().issue(currency=request.currency, limit=limit, expires_on=expires_on)
    card = VendorCard(id=uuid.uuid4(), org_id=user.org_id, request_id=request.id, holder_id=request.requested_by,
                      issued_by=user.id, issuer_ref=issuer_ref, last4=last4, currency=request.currency,
                      limit_amount=limit, merchant_lock=(merchant_lock or "").strip()[:120] or None, expires_on=expires_on)
    db.add(card)
    db.flush()
    audit(db, card, user.id, "issued", {"request_id": request.id, "limit": limit, "expires_on": expires_on.isoformat(),
                                        "merchant_lock": card.merchant_lock, "simulated": True})
    return card


def _decline_reason(card: VendorCard, merchant: str, amount: Decimal) -> str | None:
    if card.status != "active":
        return f"The card is {card.status}."
    if card.expires_on < date.today():
        return "The card has expired."
    if card.merchant_lock and merchant.strip().casefold() != card.merchant_lock.casefold():
        return f"The card only works at {card.merchant_lock}."
    if amount <= 0:
        return "The amount must be above zero."
    if card.spent + amount > card.limit_amount:
        return f"The charge would pass the card's limit ({card.limit_amount - card.spent} left)."
    return None


def simulate_charge(db: Session, user: User, card_id: uuid.UUID, *, merchant: str, amount: Decimal) -> CardTransaction:
    """Pretend a merchant charged the card. Used for demos and tests; the decision follows the rules above."""
    card = load(db, user, card_id, lock=True)
    reason = _decline_reason(card, merchant, amount)
    tx = CardTransaction(org_id=card.org_id, card_id=card.id, merchant=merchant.strip()[:120], amount=amount,
                         status="declined" if reason else "approved", decline_reason=reason,
                         auth_code=None if reason else secrets.token_hex(3).upper())
    if reason is None:
        card.spent += amount
    db.add(tx)
    db.flush()
    audit(db, card, user.id, "charge_declined" if reason else "charge_approved",
          {"merchant": tx.merchant, "amount": amount, "reason": reason, "simulated": True})
    return tx


def set_status(db: Session, user: User, card_id: uuid.UUID, status: str) -> VendorCard:
    card = load(db, user, card_id, lock=True)
    if status not in ("active", "frozen", "closed"):
        raise Invalid("Status must be active, frozen or closed.")
    if card.status == "closed":
        raise Conflict("A closed card cannot be reopened. Issue a new one.")
    # The holder can only make their card safer (freeze); anything else needs finance or an admin.
    if user.role not in ISSUER_ROLES and status != "frozen":
        raise Forbidden("Only finance or an admin can unfreeze or close a card.")
    if card.status != status:
        old, card.status = card.status, status
        get_issuer().set_state(card.issuer_ref, status)
        audit(db, card, user.id, f"card_{status}", {"from": old})
    return card
