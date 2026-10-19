"""The Rules page: every control as an IF/THEN card, and the few an admin may edit (BUILD_PLAN v2.3 change 24).

Editable here: approval tiers (§9) and which buyer owns each category. Each edit is one
transaction with its audit event. Tier edits deactivate the old rows (history is kept) and
apply only to approval chains started afterwards: a chain is copied into request_approvals
when it starts (procurement `_start_chain`), so requests already in approval are unaffected.

Read-only here: segregation of duties (§9, enforced in code) and the matching rules (§6),
whose tolerances change only through a reviewed code release (`matching/config.py`).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Invalid, NotFound
from app.models import ApprovalPolicy, Category, Org, User
from app.modules.audit.service import record_event
from app.modules.matching.config import RISK_WEIGHTS, RULE_SET_VERSION, Tolerances

CENT = Decimal("0.01")
# Roles a tier step may require. "manager" means the requester's own manager (users.manager_id).
STEP_ROLES = ("manager", "approver", "finance", "admin")
MAX_TIERS = 10
EDITOR_ROLES = ("admin",)
# All tier edits for an org chain under one audit entity, derived from the org id so it is stable.
_TIERS_NAMESPACE = uuid.UUID("6f1d3c52-6a43-4d55-9a3c-0b7f1a0e2b11")


def tiers_entity_id(org_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_TIERS_NAMESPACE, str(org_id))


@dataclass
class TierInput:
    min_amount: Decimal
    max_amount: Decimal | None
    steps: list[str]


SOD_RULES = [
    ("A requester tries to approve their own request", "Refused (403)"),
    ("The buyer who completed a request tries to approve it", "Refused (403)"),
    ("One person tries to approve two steps of the same request", "Refused (403)"),
    ("A step is decided before the step before it", "Refused (409)"),
    ("An approval is above the approver's limit", "Refused (403)"),
    ("The person who uploaded or edited an invoice tries to approve it", "Refused (403)"),
    ("The amount of a request changes after approval started", "The approval chain restarts"),
    ("An invoice has an open question to someone", "Approval waits until they answer (409)"),
    ("The person asked about an invoice tries to approve it", "Refused (403)"),
    ("A category's named reviewer step is decided by anyone else", "Refused (403)"),
]


def _matching_cards() -> list[dict[str, str]]:
    t = Tolerances()
    price = f"{t.price_pct * 100:.0f}%"
    return [
        {"if": "An invoice line cannot be paired to a PO line by PO line reference, item code, or HSN + rate "
               f"within {t.pairing_rate_pct * 100:.0f}%", "then": "Exception LINE_UNPAIRED (descriptions never pass a line)"},
        {"if": "Quantity invoiced to date would exceed quantity received", "then": "Exception QTY_EXCEEDS_RECEIPT"},
        {"if": f"Invoice rate differs from the PO rate by more than {price}", "then": "Exception PRICE_VARIANCE"},
        {"if": f"Lines, tax and total do not add up within ₹{t.arithmetic_abs}", "then": "Exception ARITHMETIC_MISMATCH"},
        {"if": "The invoice GSTIN is not the PO vendor's GSTIN", "then": "Exception VENDOR_MISMATCH"},
        {"if": "Same state but IGST charged, or different states but CGST + SGST charged", "then": "Exception TAX_TYPE_MISMATCH"},
        {"if": "Same vendor, invoice number and financial year as an earlier invoice",
         "then": "Warning DUPLICATE_SUSPECTED; with the same total too, blocking DUPLICATE_BLOCKING"},
        {"if": "The PO is closed or cancelled", "then": "Exception PO_NOT_OPEN"},
        {"if": "The PO or receipt changed in the ERP after matching", "then": "The match is stale and must be re-run"},
    ]


def _active_tiers(db: Session, org_id: uuid.UUID) -> list[ApprovalPolicy]:
    return list(db.scalars(select(ApprovalPolicy).where(ApprovalPolicy.org_id == org_id, ApprovalPolicy.active)
                           .order_by(ApprovalPolicy.min_amount)))


def tier_json(policy: ApprovalPolicy) -> dict[str, Any]:
    return {"min_amount": policy.min_amount, "max_amount": policy.max_amount, "steps": list(policy.steps)}


def overview(db: Session, user: User) -> dict[str, Any]:
    buyers = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    categories = db.scalars(select(Category).where(Category.org_id == user.org_id, Category.active)
                            .order_by(Category.name)).all()
    return {
        "can_edit": user.role in EDITOR_ROLES,
        "step_roles": list(STEP_ROLES),
        "approval_tiers": [tier_json(p) for p in _active_tiers(db, user.org_id)],
        "categories": [{"id": c.id, "name": c.name, "buyer_id": c.buyer_id,
                        "buyer_name": buyers.get(c.buyer_id), "extra_approver_id": c.extra_approver_id,
                        "extra_approver_name": buyers.get(c.extra_approver_id),
                        "extra_step_label": c.extra_step_label} for c in categories],
        "segregation_of_duties": [{"if": i, "then": t} for i, t in SOD_RULES],
        "matching": {
            "rule_set_version": RULE_SET_VERSION,
            "tolerances": Tolerances().as_json(),
            "risk_weights": RISK_WEIGHTS,
            "rules": _matching_cards(),
        },
    }


def validate_tiers(tiers: list[TierInput]) -> list[TierInput]:
    """Tiers must cover every amount from ₹0 upwards exactly once, so any request finds one tier."""
    if not tiers:
        raise Invalid("Add at least one approval tier.")
    if len(tiers) > MAX_TIERS:
        raise Invalid(f"At most {MAX_TIERS} approval tiers.")
    ordered = sorted(tiers, key=lambda t: t.min_amount)
    for tier in ordered:
        for amount in (tier.min_amount, tier.max_amount):
            if amount is not None and (amount < 0 or amount != amount.quantize(CENT)):
                raise Invalid("Tier amounts must be zero or more, in rupees and paise.")
        if not tier.steps:
            raise Invalid("Every tier needs at least one approval step.")
        unknown = [s for s in tier.steps if s not in STEP_ROLES]
        if unknown:
            raise Invalid(f"Unknown approval step: {', '.join(unknown)}.")
        if len(set(tier.steps)) != len(tier.steps):
            # One person may not approve two steps (§9), so the same role twice could never complete.
            raise Invalid("A tier cannot list the same step twice.")
    if ordered[0].min_amount != 0:
        raise Invalid("The first tier must start at ₹0.")
    for current, following in zip(ordered, ordered[1:], strict=False):
        if current.max_amount is None:
            raise Invalid("Only the last tier can be open-ended.")
        if current.max_amount < current.min_amount:
            raise Invalid(f"A tier ends (₹{current.max_amount}) before it starts (₹{current.min_amount}).")
        if following.min_amount != current.max_amount + CENT:
            raise Invalid(f"Tiers must not overlap or leave gaps: after ₹{current.max_amount} the next tier "
                          f"must start at ₹{current.max_amount + CENT}.")
    if ordered[-1].max_amount is not None:
        raise Invalid("The last tier must have no upper limit, so every amount is covered.")
    return ordered


def replace_tiers(db: Session, user: User, tiers: list[TierInput]) -> list[ApprovalPolicy]:
    ordered = validate_tiers(tiers)
    # Lock the org row: two admins saving at once must not both deactivate and both insert.
    db.execute(select(Org.id).where(Org.id == user.org_id).with_for_update())
    old = _active_tiers(db, user.org_id)
    for policy in old:
        policy.active = False
    new = [ApprovalPolicy(org_id=user.org_id, min_amount=t.min_amount, max_amount=t.max_amount, steps=t.steps)
           for t in ordered]
    db.add_all(new)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="approval_policies", entity_id=tiers_entity_id(user.org_id),
                 actor_id=user.id, action="tiers_replaced",
                 payload={"old": [tier_json(p) for p in old], "new": [tier_json(p) for p in new],
                          "applies_to": "approval chains started after this change"})
    return new


def _active_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
    return db.scalar(select(User).where(User.id == user_id, User.org_id == org_id, User.active))


def update_category(db: Session, user: User, category_id: uuid.UUID, changes: dict) -> Category:
    """Change a category's buyer and/or its extra approval step (only the keys given in `changes`)."""
    category = db.scalar(select(Category).where(Category.id == category_id, Category.org_id == user.org_id)
                         .with_for_update())
    if category is None:
        raise NotFound("Category not found.")
    if "buyer_id" in changes and changes["buyer_id"] is not None:
        buyer = _active_user(db, user.org_id, changes["buyer_id"])
        if buyer is None or buyer.role != "buyer":
            raise Invalid("Choose an active user with the buyer role.")
    if "extra_approver_id" in changes and changes["extra_approver_id"] is not None:
        reviewer = _active_user(db, user.org_id, changes["extra_approver_id"])
        if reviewer is None or reviewer.role == "requester":
            raise Invalid("Choose an active user who is not only a requester for the extra approval step.")
        if not (changes.get("extra_step_label") or category.extra_step_label or "").strip():
            raise Invalid('Name the extra step, e.g. "IT security review".')
    old = {"buyer_id": category.buyer_id, "extra_approver_id": category.extra_approver_id,
           "extra_step_label": category.extra_step_label}
    for field in ("buyer_id", "extra_approver_id"):
        if field in changes:
            setattr(category, field, changes[field])
    if "extra_step_label" in changes:
        category.extra_step_label = (changes["extra_step_label"] or "").strip() or None
    if category.extra_approver_id is None:
        category.extra_step_label = None
    new = {"buyer_id": category.buyer_id, "extra_approver_id": category.extra_approver_id,
           "extra_step_label": category.extra_step_label}
    action = "buyer_changed" if set(changes) == {"buyer_id"} else "category_rules_changed"
    record_event(db, org_id=user.org_id, entity_type="category", entity_id=category.id, actor_id=user.id,
                 action=action, payload={"old": old, "new": new, "new_buyer_id": category.buyer_id,
                                         "applies_to": "requests submitted or sent for approval after this change"})
    return category
