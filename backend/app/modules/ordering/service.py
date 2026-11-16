"""Orrfin purchase orders that procurement builds from approved needs (Step 42, ADR 0012; BUILD_PLAN §1, §8, §9).

The real-world order this follows: an employee states a need (item and quantity, no vendor), their
manager approves it (modules/procurement), and procurement collects the approved needs, picks the
vendor and the price, and raises one PO per vendor. The same item asked for by several people becomes
one PO line (20 boxes from Riya + 10 from Sameer = one line of 30), as in ERPNext "Get Items From
Material Request" and Precoro "PO from requisitions".

Lifecycle of an Orrfin PO (PO-0001):
  draft → (submit) → in_approval → approved → sent;   draft/returned → cancelled;   in_approval → rejected | returned.
- The approval chain is the org's amount tiers *without* the manager step: the manager already approved
  each need. With the demo tiers: up to ₹50,000 no approval; up to ₹5 lakh Finance; above that Finance
  and an admin. A PO with no steps is approved when submitted.
- Segregation of duties (§9): the person who built or submitted the PO cannot approve it, and nobody
  decides two steps of one PO.
- On approval the ERP draft PO is queued in the same transaction (§8). "Send to vendor" waits for the
  ERP to confirm the draft, so the email carries the ERP's PO number and the supplier's invoice will
  quote it (which keeps 3-way matching working).
- Sending is simulated: the email is stored in `vendor_messages` and printed by the console sender.

Every state change writes its audit event in the same transaction (the router commits).
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, DomainError, Forbidden, Invalid, NotFound
from app.models import (
    Category,
    Org,
    OrderPo,
    OrderPoApproval,
    OrderPoLine,
    OrderPoLineSource,
    PoLine,
    PurchaseOrder,
    PurchaseRequest,
    RequestLine,
    Supplier,
    User,
    Vendor,
    VendorMessage,
)
from app.modules.audit.service import record_event
from app.modules.erp_outbox import service as outbox_service
from app.modules.erp_outbox.po import order_reference, queue_order_po, vendor_unavailable_reason
from app.modules.notifications.service import notify
from app.modules.procurement import service as procurement

log = logging.getLogger(__name__)

BUILD_ROLES = ("buyer", "admin")
VIEW_ROLES = ("buyer", "admin", "finance", "approver")
EDITABLE = ("draft", "returned")
CANCELLABLE = ("draft", "returned", "in_approval")
# Statuses whose lines still hold their request lines; cancelled and rejected POs free them.
LIVE = ("draft", "in_approval", "returned", "approved", "sent")
# Request statuses an Orrfin PO moves between as its lines are placed and sent.
ORDER_DRIVEN = ("with_buyer", "po_drafted", "po_open")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class PoLineInput:
    item_code: str
    rate: Decimal
    request_line_ids: list[uuid.UUID]
    description: str | None = None
    unit: str | None = None
    hsn: str | None = None


@dataclass
class LineChange:
    id: uuid.UUID
    item_code: str | None = None
    description: str | None = None
    rate: Decimal | None = None
    hsn: str | None = None


@dataclass
class Readiness:
    allowed: bool
    reason: str | None
    erp_doc_name: str | None = None
    notes: list[str] = field(default_factory=list)


def po_number(n: int) -> str:
    return f"PO-{n:04d}"


def _audit(db: Session, po: OrderPo, actor: User | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=po.org_id, entity_type="order_po", entity_id=po.id,
                 actor_id=actor.id if actor else None, action=action,
                 payload={"status": po.status, "amount": po.amount, **(payload or {})})


def _require(user: User, roles: tuple[str, ...], message: str) -> None:
    if user.role not in roles:
        raise Forbidden(message)


def _require_need_first(db: Session, org_id: uuid.UUID) -> None:
    if procurement.intake_flow(db, org_id) != procurement.NEED_FIRST:
        raise Conflict("This workspace prices each request on the request itself; Orders are not used here.")


# --- Loading -------------------------------------------------------------------------------------------

def load_po(db: Session, user: User, po_id: uuid.UUID, *, lock: bool = False) -> OrderPo:
    """A PO the user may see. Requesters and other orgs get "not found"."""
    query = select(OrderPo).where(OrderPo.id == po_id, OrderPo.org_id == user.org_id)
    if lock:
        query = query.with_for_update()
    po = db.scalar(query)
    if po is None or user.role not in VIEW_ROLES:
        raise NotFound("Purchase order not found.")
    return po


def po_lines(db: Session, po: OrderPo) -> list[OrderPoLine]:
    return list(db.scalars(select(OrderPoLine).where(OrderPoLine.order_po_id == po.id).order_by(OrderPoLine.line_no)))


def current_steps(db: Session, po: OrderPo) -> list[OrderPoApproval]:
    if po.approval_round == 0:
        return []
    return list(db.scalars(select(OrderPoApproval).where(
        OrderPoApproval.order_po_id == po.id, OrderPoApproval.round == po.approval_round).order_by(OrderPoApproval.step)))


def _sources(db: Session, po: OrderPo) -> list[OrderPoLineSource]:
    return list(db.scalars(select(OrderPoLineSource).join(OrderPoLine, OrderPoLine.id == OrderPoLineSource.order_po_line_id)
                           .where(OrderPoLine.order_po_id == po.id)))


# --- Approved needs and the item list --------------------------------------------------------------------

def open_needs(db: Session, user: User) -> list[dict[str, Any]]:
    """Lines of approved needs that are not yet on a live PO: procurement's to-order list."""
    _require(user, VIEW_ROLES, "Only procurement, approvers, finance or an admin can see approved needs.")
    if procurement.intake_flow(db, user.org_id) != procurement.NEED_FIRST:
        return []
    placed = select(OrderPoLineSource.request_line_id).where(OrderPoLineSource.active)
    rows = db.execute(
        select(RequestLine, PurchaseRequest, Category.name, User.full_name)
        .join(PurchaseRequest, PurchaseRequest.id == RequestLine.request_id)
        .join(Category, Category.id == PurchaseRequest.category_id)
        .join(User, User.id == PurchaseRequest.requested_by)
        .where(PurchaseRequest.org_id == user.org_id, PurchaseRequest.status == "with_buyer",
               RequestLine.id.not_in(placed))
        .order_by(PurchaseRequest.needed_by.asc().nulls_last(), PurchaseRequest.number, RequestLine.line_no)).all()
    buyers = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    return [{
        "request_line_id": line.id, "request_id": request.id, "request_number": request.number,
        "request_title": request.title, "description": line.description, "qty": line.qty, "unit": line.unit,
        "est_rate": line.est_rate, "requester_name": requester, "category_name": category,
        "cost_center": request.cost_center, "needed_by": request.needed_by, "approved_at": request.updated_at,
        "buyer_name": buyers.get(request.assigned_buyer_id), "source_channel": request.source_channel,
    } for line, request, category, requester in rows]


def item_catalog(db: Session, user: User) -> list[dict[str, Any]]:
    """Item codes the ERP knows, with the last price paid: from the mirrored ERP purchase orders.

    Picking from this list (instead of typing a code) is what keeps the ERP from refusing the draft PO
    with "Could not find Item".
    """
    _require(user, VIEW_ROLES, "Only procurement, approvers, finance or an admin can see the item list.")
    rows = db.execute(select(PoLine, PurchaseOrder.po_date, PurchaseOrder.vendor_id)
                      .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                      .where(PoLine.org_id == user.org_id)
                      .order_by(PurchaseOrder.po_date.desc().nulls_last())).all()
    vendors = dict(db.execute(select(Vendor.id, Vendor.name).where(Vendor.org_id == user.org_id)).all())
    latest: dict[str, dict[str, Any]] = {}
    for line, po_date, vendor_id in rows:
        if line.item_code in latest:
            continue
        latest[line.item_code] = {"item_code": line.item_code, "description": line.description, "unit": line.uom,
                                  "hsn": line.hsn, "last_rate": line.rate, "last_date": po_date,
                                  "last_vendor": vendors.get(vendor_id)}
    return sorted(latest.values(), key=lambda item: item["item_code"])


# --- Building a PO -----------------------------------------------------------------------------------------

def _locked_request_lines(db: Session, user: User, ids: list[uuid.UUID]) -> dict[uuid.UUID, RequestLine]:
    lines = {line.id: line for line in db.scalars(
        select(RequestLine).where(RequestLine.id.in_(ids), RequestLine.org_id == user.org_id)
        .order_by(RequestLine.id).with_for_update())}  # fixed order: two buyers can't deadlock
    missing = set(ids) - set(lines)
    if missing:
        raise Invalid("A chosen need does not exist or belongs to another workspace.")
    taken = set(db.scalars(select(OrderPoLineSource.request_line_id).where(
        OrderPoLineSource.request_line_id.in_(ids), OrderPoLineSource.active)))
    if taken:
        raise Conflict("Some of these needs are already on another purchase order. Refresh the list.")
    statuses = dict(db.execute(select(PurchaseRequest.id, PurchaseRequest.status).where(
        PurchaseRequest.id.in_({line.request_id for line in lines.values()}))).all())
    if any(statuses[line.request_id] != "with_buyer" for line in lines.values()):
        raise Conflict("Only needs approved by a manager and waiting for procurement can go on a PO.")
    return lines


def _merge(lines: list[PoLineInput]) -> list[PoLineInput]:
    """Same item code at the same rate → one PO line. Different rates stay separate lines."""
    merged: dict[tuple[str, Decimal], PoLineInput] = {}
    for line in lines:
        key = (line.item_code.strip(), line.rate)
        if key in merged:
            merged[key].request_line_ids.extend(line.request_line_ids)
        else:
            merged[key] = PoLineInput(item_code=line.item_code.strip(), rate=line.rate,
                                      request_line_ids=list(line.request_line_ids), description=line.description,
                                      unit=line.unit, hsn=line.hsn)
    return list(merged.values())


def _vendor(db: Session, user: User, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.scalar(select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == user.org_id))
    if vendor is None:
        raise Invalid("Choose a vendor from the ERP vendor list.")
    return vendor


def create_po(db: Session, user: User, *, vendor_id: uuid.UUID, lines: list[PoLineInput],
              needed_by: date | None = None, note_to_vendor: str = "") -> OrderPo:
    _require(user, BUILD_ROLES, "Only procurement or an admin can create a purchase order.")
    _require_need_first(db, user.org_id)
    _vendor(db, user, vendor_id)
    if not lines:
        raise Invalid("Choose at least one approved need.")
    ids = [i for line in lines for i in line.request_line_ids]
    if not all(line.request_line_ids for line in lines):
        raise Invalid("Every PO line must order at least one approved need.")
    if len(ids) != len(set(ids)):
        raise Invalid("A need can appear only once on a purchase order.")
    for number, line in enumerate(lines, start=1):
        if not line.item_code.strip():
            raise Invalid(f"Line {number}: choose the ERP item code.")
        if line.rate <= 0:
            raise Invalid(f"Line {number}: the rate must be above ₹0.")
    request_lines = _locked_request_lines(db, user, ids)
    requests = {r.id: r for r in db.scalars(select(PurchaseRequest).where(
        PurchaseRequest.id.in_({line.request_id for line in request_lines.values()})))}

    number = (db.scalar(select(func.max(OrderPo.number)).where(OrderPo.org_id == user.org_id)) or 0) + 1
    dates = [r.needed_by for r in requests.values() if r.needed_by]
    po = OrderPo(id=uuid.uuid4(), org_id=user.org_id, number=number, vendor_id=vendor_id, created_by_id=user.id,
                 status="draft", needed_by=needed_by or (min(dates) if dates else None),
                 note_to_vendor=note_to_vendor.strip())
    db.add(po)
    db.flush()
    total = Decimal("0.00")
    for line_no, line in enumerate(_merge(lines), start=1):
        sources = [request_lines[i] for i in line.request_line_ids]
        qty = sum((s.qty for s in sources), Decimal("0"))
        amount = procurement.line_amount(qty, line.rate)
        total += amount
        row = OrderPoLine(org_id=user.org_id, order_po_id=po.id, line_no=line_no, item_code=line.item_code,
                          description=(line.description or sources[0].description).strip()[:300],
                          unit=(line.unit or sources[0].unit or None), qty=qty, rate=line.rate, amount=amount,
                          hsn=(line.hsn or "").strip() or None)
        db.add(row)
        db.flush()
        for source in sources:
            db.add(OrderPoLineSource(org_id=user.org_id, order_po_line_id=row.id, request_line_id=source.id,
                                     request_id=source.request_id, qty=source.qty))
    po.amount = total
    db.flush()
    _audit(db, po, user, "created", {"vendor_id": vendor_id,
                                     "requests": sorted(f"PR-{r.number:04d}" for r in requests.values())})
    for request in requests.values():
        procurement._audit(db, request, user, "placed_on_po", {"po": po_number(po.number), "po_id": po.id})
    _refresh_requests(db, set(requests), user)
    return po


def _refresh_requests(db: Session, request_ids: set[uuid.UUID], actor: User | None) -> None:
    """Move each request to the status its lines' POs imply: all lines sent → po_open ("Ordered");
    all lines on a live PO → po_drafted ("On a PO"); otherwise with_buyer ("With procurement")."""
    for request_id in sorted(request_ids):
        request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == request_id).with_for_update())
        if request is None or request.status not in ORDER_DRIVEN:
            continue
        line_ids = set(db.scalars(select(RequestLine.id).where(RequestLine.request_id == request_id)))
        placed = dict(db.execute(
            select(OrderPoLineSource.request_line_id, OrderPo.status)
            .join(OrderPoLine, OrderPoLine.id == OrderPoLineSource.order_po_line_id)
            .join(OrderPo, OrderPo.id == OrderPoLine.order_po_id)
            .where(OrderPoLineSource.request_id == request_id, OrderPoLineSource.active)).all())
        if line_ids and all(placed.get(i) == "sent" for i in line_ids):
            wanted = "po_open"
        elif line_ids and all(i in placed for i in line_ids):
            wanted = "po_drafted"
        else:
            wanted = "with_buyer"
        if wanted != request.status:
            previous, request.status = request.status, wanted
            procurement._audit(db, request, actor, "order_status_changed", {"from": previous})


def update_po(db: Session, user: User, po_id: uuid.UUID, *, vendor_id: uuid.UUID | None = None,
              needed_by: date | None = None, note_to_vendor: str | None = None,
              lines: list[LineChange] | None = None) -> OrderPo:
    _require(user, BUILD_ROLES, "Only procurement or an admin can change a purchase order.")
    po = load_po(db, user, po_id, lock=True)
    if po.status not in EDITABLE:
        raise Conflict("A purchase order can only be changed while it is a draft or returned to procurement.")
    if vendor_id is not None:
        _vendor(db, user, vendor_id)
        po.vendor_id = vendor_id
    if needed_by is not None:
        po.needed_by = needed_by
    if note_to_vendor is not None:
        po.note_to_vendor = note_to_vendor.strip()
    existing = {line.id: line for line in po_lines(db, po)}
    for change in lines or []:
        line = existing.get(change.id)
        if line is None:
            raise Invalid("A line does not belong to this purchase order.")
        if change.item_code is not None:
            if not change.item_code.strip():
                raise Invalid(f"Line {line.line_no}: choose the ERP item code.")
            line.item_code = change.item_code.strip()
        if change.description is not None and change.description.strip():
            line.description = change.description.strip()[:300]
        if change.rate is not None:
            if change.rate <= 0:
                raise Invalid(f"Line {line.line_no}: the rate must be above ₹0.")
            line.rate = change.rate
            line.amount = procurement.line_amount(line.qty, line.rate)
        if change.hsn is not None:
            line.hsn = change.hsn.strip() or None
    po.amount = sum((line.amount for line in existing.values()), Decimal("0.00"))
    _audit(db, po, user, "edited", {"vendor_id": po.vendor_id})
    return po


def cancel_po(db: Session, user: User, po_id: uuid.UUID, reason: str | None) -> OrderPo:
    _require(user, BUILD_ROLES, "Only procurement or an admin can cancel a purchase order.")
    po = load_po(db, user, po_id, lock=True)
    if po.status not in CANCELLABLE:
        raise Conflict("Only a purchase order that is not yet approved can be cancelled.")
    po.status = "cancelled"
    _release(db, po, user)
    _audit(db, po, user, "cancelled", {"reason": (reason or "").strip() or None})
    return po


def _release(db: Session, po: OrderPo, actor: User) -> None:
    """Free the request lines of a cancelled or rejected PO, so procurement can order them again."""
    sources = _sources(db, po)
    for source in sources:
        source.active = False
    db.flush()
    _refresh_requests(db, {s.request_id for s in sources}, actor)


# --- Approval ------------------------------------------------------------------------------------------------

def po_chain(db: Session, org_id: uuid.UUID, amount: Decimal) -> list[str]:
    """The org's amount tier for this PO, minus "manager": each need on it was approved by a manager already."""
    return [role for role in procurement._policy_steps(db, org_id, amount) if role != "manager"]


def submit_po(db: Session, user: User, po_id: uuid.UUID) -> OrderPo:
    _require(user, BUILD_ROLES, "Only procurement or an admin can submit a purchase order.")
    po = load_po(db, user, po_id, lock=True)
    if po.status not in EDITABLE:
        raise Conflict("This purchase order has already been submitted.")
    if po.amount <= 0 or not po_lines(db, po):
        raise Invalid("The purchase order needs at least one priced line.")
    steps = po_chain(db, po.org_id, po.amount)
    po.completed_by_id = user.id
    if not steps:
        po.status = "approved"
        _audit(db, po, user, "approved", {"by_tier": True, "steps": []})
        queue_order_po(db, po, user.id)  # §8: outbox row in the same transaction as the approval
        return po
    po.approval_round += 1
    for number, role in enumerate(steps, start=1):
        db.add(OrderPoApproval(org_id=po.org_id, order_po_id=po.id, round=po.approval_round, step=number,
                               required_role=role))
    po.status = "in_approval"
    db.flush()
    _audit(db, po, user, "sent_for_approval", {"round": po.approval_round, "steps": steps})
    _notify_role(db, po, steps[0])
    return po


def _notify_role(db: Session, po: OrderPo, role: str) -> None:
    for person in db.scalars(select(User).where(User.org_id == po.org_id, User.role == role, User.active)):
        if person.id != po.completed_by_id:
            notify(db, org_id=po.org_id, user_id=person.id, kind="po_to_approve",
                   title=f"{po_number(po.number)} needs your approval", body=f"₹{po.amount:,.2f}",
                   link=f"/orders/{po.id}")


def decision_refusal(db: Session, user: User, po: OrderPo, steps: list[OrderPoApproval], step_number: int,
                     decision: str) -> DomainError | None:
    """Why `user` may not decide step `step_number` now, or None. Same order of checks as requests."""
    if po.status != "in_approval":
        return Conflict("This purchase order is not waiting for approval.")
    step = next((s for s in steps if s.step == step_number), None)
    if step is None:
        return NotFound("That approval step does not exist.")
    if step.decision is not None:
        return Conflict(f"Step {step_number} has already been decided.")
    if any(s.decision is None for s in steps if s.step < step_number):
        return Conflict(f"Step {step_number} cannot be decided before the earlier steps.")
    if user.id in (po.created_by_id, po.completed_by_id):
        return Forbidden("You built this purchase order, so someone else must approve it.")
    if any(s.approver_id == user.id for s in steps if s.step != step_number):
        return Forbidden("You have already approved another step of this purchase order.")
    if user.role != step.required_role:
        return Forbidden(f"This step needs the {step.required_role} role.")
    if decision == "approve" and po.amount > user.approval_limit:
        return Forbidden(f"₹{po.amount} is above your approval limit of ₹{user.approval_limit}.")
    return None


def next_step_for(db: Session, user: User, po: OrderPo, steps: list[OrderPoApproval] | None = None) -> int | None:
    steps = current_steps(db, po) if steps is None else steps
    pending = next((s for s in steps if s.decision is None), None)
    if pending is None:
        return None
    return pending.step if decision_refusal(db, user, po, steps, pending.step, "return") is None else None


def decide_po(db: Session, user: User, po_id: uuid.UUID, step_number: int, decision: str,
              reason: str | None) -> OrderPo:
    if decision not in ("approve", "reject", "return"):
        raise Invalid("Decision must be approve, reject or return.")
    reason = (reason or "").strip() or None
    if decision in ("reject", "return") and not reason:
        raise Invalid("Give a reason when you reject or return a purchase order.")
    po = load_po(db, user, po_id, lock=True)
    steps = current_steps(db, po)
    refusal = decision_refusal(db, user, po, steps, step_number, decision)
    if refusal is not None:
        raise refusal
    step = next(s for s in steps if s.step == step_number)
    step.approver_id, step.decision, step.reason, step.decided_at = user.id, decision, reason, datetime.now(UTC)
    payload = {"step": step_number, "round": po.approval_round, "required_role": step.required_role, "reason": reason}
    if decision == "reject":
        po.status = "rejected"
        _release(db, po, user)
        _audit(db, po, user, "rejected", payload)
    elif decision == "return":
        po.status = "returned"
        _audit(db, po, user, "returned", payload)
    elif all(s.decision == "approve" for s in steps):
        po.status = "approved"
        _audit(db, po, user, "approved", payload)
        queue_order_po(db, po, user.id)  # §8 "Trigger": same transaction as the final approval
    else:
        _audit(db, po, user, "step_approved", payload)
        following = next((s for s in steps if s.decision is None), None)
        if following is not None:
            _notify_role(db, po, following.required_role)
    if po.status != "in_approval":
        notify(db, org_id=po.org_id, user_id=po.completed_by_id or po.created_by_id, kind=f"po_{po.status}",
               title=f"{po_number(po.number)} was {po.status}", body=reason or "", link=f"/orders/{po.id}")
    return po


# --- Sending to the vendor (simulated) -------------------------------------------------------------------------

def send_readiness(db: Session, po: OrderPo) -> Readiness:
    if po.status == "sent":
        return Readiness(False, "Already sent to the vendor.")
    if po.status != "approved":
        return Readiness(False, "The purchase order must be approved before it goes to the vendor.")
    row = outbox_service.outbox_for(db, order_po_id=po.id)
    if row is None:
        reason = vendor_unavailable_reason(db, po.org_id, po.vendor_id)
        return Readiness(True, None, None, [f"No ERP draft: {reason} The email carries the Orrfin PO number."])
    if row.state == "CONFIRMED":
        return Readiness(True, None, row.erp_doc_name)
    if row.state == "FAILED":
        return Readiness(False, f"The ERP refused the draft PO: {row.last_error} Fix it, then use Retry sync.")
    return Readiness(False, "Waiting for the ERP to confirm the draft PO (usually a few seconds).")


def vendor_email(db: Session, vendor: Vendor) -> str:
    """The supplier contact from onboarding, if this ERP vendor came through the supplier portal."""
    return db.scalar(select(Supplier.contact_email).where(Supplier.vendor_id == vendor.id).limit(1)) or ""


def compose(db: Session, po: OrderPo, *, note: str | None = None) -> dict[str, Any]:
    """The email and WhatsApp text procurement sends. Built from the record; nothing is sent."""
    org = db.get(Org, po.org_id)
    vendor = db.get(Vendor, po.vendor_id)
    buyer = db.get(User, po.completed_by_id or po.created_by_id)
    erp_doc = send_readiness(db, po).erp_doc_name
    reference = f"{po_number(po.number)}" + (f" / {erp_doc}" if erp_doc else "")
    lines = po_lines(db, po)
    note = po.note_to_vendor if note is None else note.strip()
    rows = [f"{line.line_no}. {line.description} ({line.item_code}): {line.qty.normalize():f} "
            f"{line.unit or 'nos'} × ₹{line.rate:,.2f} = ₹{line.amount:,.2f}" for line in lines]
    deliver_by = f"{po.needed_by:%d %b %Y}" if po.needed_by else "the earliest date you can confirm"
    body = "\n".join([
        f"Dear {vendor.name} team,", "",
        f"Please find attached our purchase order {reference} for the following requirements:", "",
        *rows, "", f"Total (before GST): ₹{po.amount:,.2f}", f"Please deliver by: {deliver_by}", "",
        *([note, ""] if note else []),
        f"Kindly confirm receipt of this order and the delivery date, and quote {erp_doc or po_number(po.number)} "
        "on your invoice.", "",
        "Regards,", buyer.full_name, f"Procurement, {org.name}",
    ])
    whatsapp = "\n".join([f"*Purchase order {reference}* from {org.name}", *rows,
                          f"Total ₹{po.amount:,.2f} · deliver by {deliver_by}",
                          "PDF sent by email. Please confirm receipt."])
    return {"to": vendor_email(db, vendor), "subject": f"Purchase Order {reference} from {org.name}",
            "body": body, "whatsapp": whatsapp, "attachment_name": f"{po_number(po.number)}.pdf",
            "reference": reference}


def send_po(db: Session, user: User, po_id: uuid.UUID, *, to: str, note: str | None = None) -> OrderPo:
    _require(user, BUILD_ROLES, "Only procurement or an admin can send a purchase order.")
    po = load_po(db, user, po_id, lock=True)
    ready = send_readiness(db, po)
    if not ready.allowed:
        raise Conflict(ready.reason or "This purchase order cannot be sent yet.")
    to = to.strip()
    if not _EMAIL.match(to):
        raise Invalid("Enter the vendor's email address.")
    message = compose(db, po, note=note)
    db.add(VendorMessage(org_id=po.org_id, order_po_id=po.id, channel="email", to_address=to,
                         subject=message["subject"], body=message["body"],
                         attachment_name=message["attachment_name"], created_by_id=user.id))
    log.info("EMAIL (console sender) to=%s subject=%s attachment=%s", to, message["subject"], message["attachment_name"])
    po.status, po.sent_at, po.sent_by_id = "sent", datetime.now(UTC), user.id
    _audit(db, po, user, "sent_to_vendor", {"to": to, "subject": message["subject"], "erp_doc_name": ready.erp_doc_name,
                                           "simulated": True})
    sources = _sources(db, po)
    _refresh_requests(db, {s.request_id for s in sources}, user)
    for request in db.scalars(select(PurchaseRequest).where(PurchaseRequest.id.in_({s.request_id for s in sources}))):
        notify(db, org_id=po.org_id, user_id=request.requested_by, kind="request_ordered",
               title=f"PR-{request.number:04d} is ordered on {message['reference']}", body=request.title,
               link=f"/requests/{request.id}")
    return po


# --- Shaping ---------------------------------------------------------------------------------------------------

def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all()) if ids else {}


def summaries(db: Session, user: User) -> list[dict[str, Any]]:
    _require(user, VIEW_ROLES, "Only procurement, approvers, finance or an admin can see purchase orders.")
    pos = list(db.scalars(select(OrderPo).where(OrderPo.org_id == user.org_id).order_by(OrderPo.number.desc())))
    if not pos:
        return []
    vendors = dict(db.execute(select(Vendor.id, Vendor.name).where(Vendor.id.in_({p.vendor_id for p in pos}))).all())
    names = _names(db, {p.created_by_id for p in pos})
    covered: dict[uuid.UUID, set[int]] = {}
    for po_id, number in db.execute(
            select(OrderPoLine.order_po_id, PurchaseRequest.number)
            .join(OrderPoLineSource, OrderPoLineSource.order_po_line_id == OrderPoLine.id)
            .join(PurchaseRequest, PurchaseRequest.id == OrderPoLineSource.request_id)
            .where(OrderPoLine.order_po_id.in_([p.id for p in pos]))).all():
        covered.setdefault(po_id, set()).add(number)
    erp = dict(db.execute(select(outbox_service.ErpOutbox.order_po_id, outbox_service.ErpOutbox.erp_doc_name)
                          .where(outbox_service.ErpOutbox.order_po_id.in_([p.id for p in pos]))).all())
    out = []
    for po in pos:
        waiting = None
        if po.status == "in_approval":
            pending = next((s for s in current_steps(db, po) if s.decision is None), None)
            waiting = f"Step {pending.step}: {pending.required_role}" if pending else None
        out.append({"id": po.id, "number": po.number, "status": po.status, "amount": po.amount,
                    "currency": po.currency, "vendor_name": vendors.get(po.vendor_id, ""),
                    "created_by_name": names.get(po.created_by_id, ""), "needed_by": po.needed_by,
                    "requests": [f"PR-{n:04d}" for n in sorted(covered.get(po.id, set()))],
                    "erp_doc_name": erp.get(po.id), "waiting_on": waiting, "created_at": po.created_at,
                    "sent_at": po.sent_at})
    return out


def detail(db: Session, user: User, po: OrderPo) -> dict[str, Any]:
    db.flush()
    vendor = db.get(Vendor, po.vendor_id)
    steps = current_steps(db, po)
    lines = po_lines(db, po)
    sources = _sources(db, po)
    requests = {r.id: r for r in db.scalars(select(PurchaseRequest).where(
        PurchaseRequest.id.in_({s.request_id for s in sources})))} if sources else {}
    names = _names(db, {po.created_by_id, po.completed_by_id, po.sent_by_id} | {s.approver_id for s in steps}
                   | {r.requested_by for r in requests.values()})
    by_line: dict[uuid.UUID, list[dict]] = {}
    for source in sources:
        request = requests[source.request_id]
        by_line.setdefault(source.order_po_line_id, []).append({
            "request_id": request.id, "request_number": request.number, "requester_name": names.get(request.requested_by),
            "qty": source.qty, "active": source.active})
    row = outbox_service.outbox_for(db, order_po_id=po.id)
    ready = send_readiness(db, po)
    step = next_step_for(db, user, po, steps)
    allowed = {"edit": user.role in BUILD_ROLES and po.status in EDITABLE,
               "submit": user.role in BUILD_ROLES and po.status in EDITABLE,
               "cancel": user.role in BUILD_ROLES and po.status in CANCELLABLE,
               "send": user.role in BUILD_ROLES and ready.allowed,
               "decide_step": step, "can_approve": False, "approve_blocked_reason": None}
    if step is not None:
        refusal = decision_refusal(db, user, po, steps, step, "approve")
        allowed["can_approve"] = refusal is None
        allowed["approve_blocked_reason"] = refusal.message if refusal else None
    messages = db.scalars(select(VendorMessage).where(VendorMessage.order_po_id == po.id)
                          .order_by(VendorMessage.created_at)).all()
    chain = po_chain(db, po.org_id, po.amount) if po.status in EDITABLE and po.amount > 0 else None
    return {
        "id": po.id, "number": po.number, "status": po.status, "amount": po.amount, "currency": po.currency,
        "vendor_id": po.vendor_id, "vendor_name": vendor.name, "vendor_gstin": vendor.gstin,
        "needed_by": po.needed_by, "note_to_vendor": po.note_to_vendor, "created_at": po.created_at,
        "created_by_name": names.get(po.created_by_id), "completed_by_name": names.get(po.completed_by_id),
        "sent_at": po.sent_at, "sent_by_name": names.get(po.sent_by_id), "approval_round": po.approval_round,
        "reference": order_reference(db, po) if sources else po_number(po.number),
        "lines": [{"id": line.id, "line_no": line.line_no, "item_code": line.item_code, "description": line.description,
                   "unit": line.unit, "qty": line.qty, "rate": line.rate, "amount": line.amount, "hsn": line.hsn,
                   "sources": by_line.get(line.id, [])} for line in lines],
        "steps": [{"step": s.step, "required_role": s.required_role, "approver_id": s.approver_id,
                   "approver_name": names.get(s.approver_id), "decision": s.decision, "reason": s.reason,
                   "decided_at": s.decided_at} for s in steps],
        "chain_preview": chain,
        "allowed": allowed,
        "erp_sync": outbox_service.status_for(db, row),
        "send_blocked_reason": None if ready.allowed else ready.reason,
        "send_notes": ready.notes,
        "messages": [{"id": m.id, "channel": m.channel, "to": m.to_address, "subject": m.subject, "body": m.body,
                      "attachment_name": m.attachment_name, "at": m.created_at,
                      "by": names.get(m.created_by_id) or _names(db, {m.created_by_id}).get(m.created_by_id)}
                     for m in messages],
    }


def placements(db: Session, request_id: uuid.UUID) -> dict[uuid.UUID, dict[str, Any]]:
    """For a request page: which live PO each of its lines is on."""
    rows = db.execute(select(OrderPoLineSource.request_line_id, OrderPo.id, OrderPo.number, OrderPo.status)
                      .join(OrderPoLine, OrderPoLine.id == OrderPoLineSource.order_po_line_id)
                      .join(OrderPo, OrderPo.id == OrderPoLine.order_po_id)
                      .where(OrderPoLineSource.request_id == request_id, OrderPoLineSource.active)).all()
    return {line_id: {"po_id": po_id, "po_number": po_number(number), "po_status": status}
            for line_id, po_id, number, status in rows}
