"""Intake-to-procure workflow: requests, routing, approval chain, segregation of duties (BUILD_PLAN §1, §9).

Lifecycle:  draft → (submit) → with_buyer | submitted (admin queue) → (buyer sends) → in_approval
            → approved | rejected | returned (requester edits and resubmits).
Every function here locks the request row, checks the rules, changes state and writes
exactly one audit event, all in the caller's transaction (the router commits). A refused
action raises before anything is written, so it leaves no trace but the error.

The approval rules live in `decision_refusal`, which the UI's "allowed actions" also use,
so a button is only shown when the server would accept the click.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, DomainError, Forbidden, Invalid, NotFound
from app.models import (
    ApprovalPolicy,
    Category,
    PurchaseRequest,
    RequestApproval,
    RequestLine,
    User,
    Vendor,
)
from app.modules.audit.service import record_event

CENT = Decimal("0.01")
EDITABLE_BY_REQUESTER = ("draft", "returned")
BUYER_EDITABLE = ("with_buyer", "in_approval")
# Roles that may see every request in their org; a requester sees only their own.
ORG_WIDE_VIEWERS = ("buyer", "approver", "finance", "admin")


@dataclass
class LineInput:
    description: str
    qty: Decimal
    est_rate: Decimal
    hsn: str | None = None


@dataclass
class BuyerLineInput:
    id: uuid.UUID
    item_code: str
    qty: Decimal
    est_rate: Decimal
    hsn: str | None = None


def line_amount(qty: Decimal, rate: Decimal) -> Decimal:
    return (qty * rate).quantize(CENT, rounding=ROUND_HALF_UP)


# --- Loading -------------------------------------------------------------------------------------

def load_request(db: Session, user: User, request_id: uuid.UUID, *, lock: bool = False) -> PurchaseRequest:
    """Fetch a request the user may see. Another org's request, or (for a requester) someone
    else's, is "not found": the user must not learn that it exists."""
    query = select(PurchaseRequest).where(PurchaseRequest.id == request_id,
                                          PurchaseRequest.org_id == user.org_id)
    if lock:
        # Serialises concurrent actions on one request (two approvers clicking at once).
        query = query.with_for_update()
    request = db.scalar(query)
    if request is None or (user.role not in ORG_WIDE_VIEWERS and request.requested_by != user.id):
        raise NotFound("Request not found.")
    return request


def request_lines(db: Session, request: PurchaseRequest) -> list[RequestLine]:
    return list(db.scalars(select(RequestLine).where(RequestLine.request_id == request.id)
                           .order_by(RequestLine.line_no)))


def current_steps(db: Session, request: PurchaseRequest) -> list[RequestApproval]:
    if request.approval_round == 0:
        return []
    return list(db.scalars(select(RequestApproval).where(
        RequestApproval.request_id == request.id, RequestApproval.round == request.approval_round,
    ).order_by(RequestApproval.step)))


def _audit(db: Session, request: PurchaseRequest, actor: User, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=request.org_id, entity_type="purchase_request", entity_id=request.id,
                 actor_id=actor.id, action=action, payload={"status": request.status, **(payload or {})})


# --- Requester -----------------------------------------------------------------------------------

def _category(db: Session, user: User, category_id: uuid.UUID) -> Category:
    category = db.scalar(select(Category).where(Category.id == category_id, Category.org_id == user.org_id,
                                                Category.active))
    if category is None:
        raise Invalid("Choose a category from the list.")
    return category


def _replace_lines(db: Session, request: PurchaseRequest, lines: list[LineInput]) -> None:
    if not lines:
        raise Invalid("Add at least one line.")
    for line in request_lines(db, request):
        db.delete(line)
    db.flush()
    total = Decimal("0.00")
    for number, line in enumerate(lines, start=1):
        if line.qty <= 0 or line.est_rate < 0:
            raise Invalid(f"Line {number}: quantity must be above 0 and the rate cannot be negative.")
        amount = line_amount(line.qty, line.est_rate)
        total += amount
        db.add(RequestLine(org_id=request.org_id, request_id=request.id, line_no=number,
                           description=line.description.strip(), qty=line.qty, est_rate=line.est_rate,
                           amount=amount, hsn=line.hsn))
    request.amount = total


def create_request(db: Session, user: User, *, category_id: uuid.UUID, title: str, justification: str,
                   cost_center: str, needed_by: date | None, lines: list[LineInput],
                   suggested_vendor_id: uuid.UUID | None = None) -> PurchaseRequest:
    _category(db, user, category_id)
    if suggested_vendor_id and db.scalar(select(Vendor.id).where(
            Vendor.id == suggested_vendor_id, Vendor.org_id == user.org_id)) is None:
        raise Invalid("Choose a suggested vendor from the list.")
    number = (db.scalar(select(func.max(PurchaseRequest.number))
                        .where(PurchaseRequest.org_id == user.org_id)) or 0) + 1
    request = PurchaseRequest(
        id=uuid.uuid4(), org_id=user.org_id, number=number, requested_by=user.id, category_id=category_id,
        title=title.strip(), justification=justification.strip(), cost_center=cost_center.strip(),
        needed_by=needed_by, suggested_vendor_id=suggested_vendor_id, status="draft",
    )
    db.add(request)
    db.flush()
    _replace_lines(db, request, lines)
    _audit(db, request, user, "created", {"amount": request.amount})
    return request


def edit_request(db: Session, user: User, request_id: uuid.UUID, *, title: str | None = None,
                 justification: str | None = None, cost_center: str | None = None,
                 needed_by: date | None = None, category_id: uuid.UUID | None = None,
                 lines: list[LineInput] | None = None) -> PurchaseRequest:
    request = load_request(db, user, request_id, lock=True)
    if request.requested_by != user.id:
        raise Forbidden("Only the requester can edit this request.")
    if request.status not in EDITABLE_BY_REQUESTER:
        raise Conflict("A request can only be edited while it is a draft or returned to you.")
    if category_id is not None:
        _category(db, user, category_id)
        request.category_id = category_id
    for field, value in (("title", title), ("justification", justification), ("cost_center", cost_center)):
        if value is not None:
            setattr(request, field, value.strip())
    if needed_by is not None:
        request.needed_by = needed_by
    if lines is not None:
        _replace_lines(db, request, lines)
    _audit(db, request, user, "edited", {"amount": request.amount})
    return request


def submit_request(db: Session, user: User, request_id: uuid.UUID) -> PurchaseRequest:
    """Route to the category's buyer (§9); a category with no buyer goes to the admin queue."""
    request = load_request(db, user, request_id, lock=True)
    if request.requested_by != user.id:
        raise Forbidden("Only the requester can submit this request.")
    if request.status not in EDITABLE_BY_REQUESTER:
        raise Conflict("This request has already been submitted.")
    if not request.title:
        raise Invalid("Give the request a title.")
    category = db.get(Category, request.category_id)
    if category.buyer_id:
        request.assigned_buyer_id, request.status = category.buyer_id, "with_buyer"
    else:
        request.assigned_buyer_id, request.status = None, "submitted"
    _audit(db, request, user, "submitted",
           {"routed_to": "buyer" if category.buyer_id else "admin_queue",
            "buyer_id": category.buyer_id, "category": category.name})
    return request


# --- Admin queue and buyer -----------------------------------------------------------------------

def assign_buyer(db: Session, user: User, request_id: uuid.UUID, buyer_id: uuid.UUID) -> PurchaseRequest:
    if user.role != "admin":
        raise Forbidden("Only an admin can assign a buyer.")
    request = load_request(db, user, request_id, lock=True)
    if request.status != "submitted":
        raise Conflict("Only requests waiting in the admin queue can be assigned.")
    buyer = db.scalar(select(User).where(User.id == buyer_id, User.org_id == user.org_id,
                                         User.role == "buyer", User.active))
    if buyer is None:
        raise Invalid("Choose a buyer from the list.")
    request.assigned_buyer_id, request.status = buyer.id, "with_buyer"
    _audit(db, request, user, "buyer_assigned", {"buyer_id": buyer.id})
    return request


def _policy_steps(db: Session, org_id: uuid.UUID, amount: Decimal) -> list[str]:
    policy = db.scalar(select(ApprovalPolicy).where(
        ApprovalPolicy.org_id == org_id, ApprovalPolicy.active,
        ApprovalPolicy.min_amount <= amount,
        (ApprovalPolicy.max_amount.is_(None)) | (ApprovalPolicy.max_amount >= amount),
    ).order_by(ApprovalPolicy.min_amount.desc()).limit(1))
    if policy is None:
        raise Conflict(f"No approval policy covers ₹{amount}. Ask an admin to add one.")
    return list(policy.steps)


def _start_chain(db: Session, request: PurchaseRequest) -> list[str]:
    """Open a new approval round. Earlier rounds stay in the table as history but no longer count."""
    steps = _policy_steps(db, request.org_id, request.amount)
    request.approval_round += 1
    for number, role in enumerate(steps, start=1):
        db.add(RequestApproval(org_id=request.org_id, request_id=request.id, round=request.approval_round,
                               step=number, required_role=role))
    db.flush()
    return steps


def buyer_update(db: Session, user: User, request_id: uuid.UUID, *, vendor_id: uuid.UUID | None,
                 lines: list[BuyerLineInput]) -> PurchaseRequest:
    """The buyer sets vendor, item codes and rates. If the amount changes during approval,
    the chain restarts (§9): approvals given for the old amount no longer count."""
    request = load_request(db, user, request_id, lock=True)
    if request.assigned_buyer_id != user.id:
        raise Forbidden("Only the buyer assigned to this request can complete it.")
    if request.status not in BUYER_EDITABLE:
        raise Conflict("The buyer can change this request only before a final decision.")
    if vendor_id is not None:
        if db.scalar(select(Vendor.id).where(Vendor.id == vendor_id, Vendor.org_id == user.org_id)) is None:
            raise Invalid("Choose a vendor from the synced ERP vendors.")
        request.vendor_id = vendor_id
    existing = {line.id: line for line in request_lines(db, request)}
    for change in lines:
        line = existing.get(change.id)
        if line is None:
            raise Invalid("A line does not belong to this request.")
        if change.qty <= 0 or change.est_rate < 0:
            raise Invalid(f"Line {line.line_no}: quantity must be above 0 and the rate cannot be negative.")
        line.item_code = change.item_code.strip() or None
        line.qty, line.est_rate = change.qty, change.est_rate
        line.amount = line_amount(change.qty, change.est_rate)
        if change.hsn is not None:
            line.hsn = change.hsn.strip() or None
    old_amount = request.amount
    request.amount = sum((line.amount for line in existing.values()), Decimal("0.00"))
    if request.status == "in_approval" and request.amount != old_amount:
        steps = _start_chain(db, request)
        _audit(db, request, user, "approval_chain_restarted",
               {"old_amount": old_amount, "amount": request.amount, "round": request.approval_round,
                "steps": steps})
    else:
        _audit(db, request, user, "buyer_updated", {"amount": request.amount, "vendor_id": request.vendor_id})
    return request


def send_for_approval(db: Session, user: User, request_id: uuid.UUID) -> PurchaseRequest:
    request = load_request(db, user, request_id, lock=True)
    if request.assigned_buyer_id != user.id:
        raise Forbidden("Only the buyer assigned to this request can send it for approval.")
    if request.status != "with_buyer":
        raise Conflict("Only a request with the buyer can be sent for approval.")
    if request.vendor_id is None:
        raise Invalid("Choose the vendor before sending for approval.")
    if any(not line.item_code for line in request_lines(db, request)):
        raise Invalid("Every line needs an item code before approval.")
    if request.amount <= 0:
        raise Invalid("The request amount must be above ₹0.")
    request.completed_by_id = user.id
    request.status = "in_approval"
    steps = _start_chain(db, request)
    _audit(db, request, user, "sent_for_approval",
           {"amount": request.amount, "round": request.approval_round, "steps": steps})
    return request


# --- Approval chain ------------------------------------------------------------------------------

def decision_refusal(db: Session, user: User, request: PurchaseRequest, steps: list[RequestApproval],
                     step_number: int, decision: str) -> DomainError | None:
    """Why `user` may not decide step `step_number` now, or None if they may. Checked in order:
    state and sequence first (409), then segregation of duties, role and limit (403)."""
    if request.status != "in_approval":
        return Conflict("This request is not waiting for approval.")
    step = next((s for s in steps if s.step == step_number), None)
    if step is None:
        return NotFound("That approval step does not exist.")
    if step.decision is not None:
        return Conflict(f"Step {step_number} has already been decided.")
    if any(s.decision is None for s in steps if s.step < step_number):
        return Conflict(f"Step {step_number} cannot be decided before the earlier steps.")
    if user.id == request.requested_by:
        return Forbidden("You cannot approve your own request.")
    if user.id == request.completed_by_id:
        return Forbidden("The buyer who completed this request cannot approve it.")
    if any(s.approver_id == user.id for s in steps if s.step != step_number):
        return Forbidden("You have already approved another step of this request.")
    if step.required_role == "manager":
        requester = db.get(User, request.requested_by)
        if requester.manager_id != user.id:
            return Forbidden("This step needs the requester's manager.")
    elif user.role != step.required_role:
        return Forbidden(f"This step needs the {step.required_role} role.")
    if decision == "approve" and request.amount > user.approval_limit:
        return Forbidden(f"₹{request.amount} is above your approval limit of ₹{user.approval_limit}.")
    return None


def decide(db: Session, user: User, request_id: uuid.UUID, step_number: int, decision: str,
           reason: str | None) -> PurchaseRequest:
    if decision not in ("approve", "reject", "return"):
        raise Invalid("Decision must be approve, reject or return.")
    reason = (reason or "").strip() or None
    if decision in ("reject", "return") and not reason:
        raise Invalid("Give a reason when you reject or return a request.")
    request = load_request(db, user, request_id, lock=True)
    steps = current_steps(db, request)
    refusal = decision_refusal(db, user, request, steps, step_number, decision)
    if refusal is not None:
        raise refusal

    step = next(s for s in steps if s.step == step_number)
    step.approver_id, step.decision, step.reason = user.id, decision, reason
    step.decided_at = datetime.now(UTC)
    payload = {"step": step_number, "round": request.approval_round, "required_role": step.required_role,
               "reason": reason, "amount": request.amount}
    if decision == "reject":
        request.status = "rejected"
        _audit(db, request, user, "rejected", payload)
    elif decision == "return":
        request.status = "returned"
        _audit(db, request, user, "returned", payload)
    elif all(s.decision == "approve" for s in steps):
        request.status = "approved"
        _audit(db, request, user, "approved", payload)
    else:
        _audit(db, request, user, "step_approved", payload)
    return request


def next_step_for(db: Session, user: User, request: PurchaseRequest,
                  steps: list[RequestApproval] | None = None) -> int | None:
    """The step this user could act on right now, if any (drives the Approvals inbox).

    Checked as a "return" decision, which skips the approval limit: an approver over their
    limit still needs to see the request, because they may reject or return it.
    """
    steps = current_steps(db, request) if steps is None else steps
    pending = next((s for s in steps if s.decision is None), None)
    if pending is None:
        return None
    return pending.step if decision_refusal(db, user, request, steps, pending.step, "return") is None else None
