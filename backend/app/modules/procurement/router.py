"""HTTP routes for procurement (BUILD_PLAN §4 procurement module; §9 routing and approval chain).

Every query filters on the logged-in user's org_id. A row from another org is
reported as 404, so a user can't even learn that it exists. Rules live in
service.py; these routes translate HTTP to service calls and commit once per action.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, DbSession
from app.models import AuditEvent, Category, PurchaseRequest, RequestApproval, User, Vendor
from app.modules.procurement import service
from app.modules.procurement.schemas import (
    AllowedActions,
    AssignBuyer,
    BuyerUpdate,
    CategoryOut,
    DecisionIn,
    LineOut,
    RequestCreate,
    RequestDetail,
    RequestEdit,
    RequestSummary,
    StepOut,
    TimelineEvent,
    UserOut,
)

router = APIRouter(tags=["procurement"])

Scope = Literal["mine", "buyer_queue", "admin_queue", "approvals", "all"]


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(user: CurrentUser, db: DbSession) -> list[Category]:
    return list(db.scalars(
        select(Category).where(Category.org_id == user.org_id, Category.active).order_by(Category.name)
    ))


@router.get("/categories/{category_id}", response_model=CategoryOut)
def get_category(category_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Category:
    category = db.scalar(select(Category).where(Category.id == category_id, Category.org_id == user.org_id))
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    return category


@router.get("/users", response_model=list[UserOut])
def list_users(user: CurrentUser, db: DbSession, role: str | None = None) -> list[User]:
    query = select(User).where(User.org_id == user.org_id, User.active).order_by(User.full_name)
    if role:
        query = query.where(User.role == role)
    return list(db.scalars(query))


# --- Shaping responses ---------------------------------------------------------------------------

def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _waiting_on(request: PurchaseRequest, steps: list[RequestApproval], names: dict) -> str | None:
    if request.status == "with_buyer":
        return f"Buyer: {names.get(request.assigned_buyer_id, 'unassigned')}"
    if request.status == "submitted":
        return "Admin queue: needs a buyer"
    if request.status == "returned":
        return "Requester: returned for changes"
    if request.status == "in_approval":
        pending = next((s for s in steps if s.decision is None), None)
        if pending:
            return f"Step {pending.step}: {pending.required_role}"
    return None


def _summaries(db: Session, requests: list[PurchaseRequest]) -> list[RequestSummary]:
    if not requests:
        return []
    categories = dict(db.execute(select(Category.id, Category.name)
                                 .where(Category.id.in_({r.category_id for r in requests}))).all())
    names = _names(db, {r.requested_by for r in requests} | {r.assigned_buyer_id for r in requests})
    steps_by_request: dict[uuid.UUID, list[RequestApproval]] = {}
    for step in db.scalars(select(RequestApproval).where(
            RequestApproval.request_id.in_([r.id for r in requests])).order_by(RequestApproval.step)):
        steps_by_request.setdefault(step.request_id, []).append(step)
    out = []
    for r in requests:
        current = [s for s in steps_by_request.get(r.id, []) if s.round == r.approval_round]
        out.append(RequestSummary(
            id=r.id, number=r.number, title=r.title, status=r.status, amount=r.amount, currency=r.currency,
            category_name=categories.get(r.category_id, ""), requester_name=names.get(r.requested_by, ""),
            buyer_name=names.get(r.assigned_buyer_id), needed_by=r.needed_by, created_at=r.created_at,
            updated_at=r.updated_at, waiting_on=_waiting_on(r, current, names)))
    return out


def _allowed(db: Session, user: User, request: PurchaseRequest, steps: list[RequestApproval]) -> AllowedActions:
    is_requester = request.requested_by == user.id
    is_buyer = request.assigned_buyer_id == user.id
    allowed = AllowedActions(
        edit=is_requester and request.status in service.EDITABLE_BY_REQUESTER,
        submit=is_requester and request.status in service.EDITABLE_BY_REQUESTER,
        assign_buyer=user.role == "admin" and request.status == "submitted",
        buyer_edit=is_buyer and request.status in service.BUYER_EDITABLE,
        send_for_approval=is_buyer and request.status == "with_buyer",
    )
    step = service.next_step_for(db, user, request, steps)
    if step is not None:
        allowed.decide_step = step
        refusal = service.decision_refusal(db, user, request, steps, step, "approve")
        allowed.can_approve = refusal is None
        allowed.approve_blocked_reason = refusal.message if refusal else None
    return allowed


def _detail(db: Session, user: User, request: PurchaseRequest) -> RequestDetail:
    db.flush()
    summary = _summaries(db, [request])[0]
    steps = service.current_steps(db, request)
    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == request.id)
                        .order_by(AuditEvent.seq)).all()
    names = _names(db, {s.approver_id for s in steps} | {e.actor_id for e in events})
    vendors = dict(db.execute(select(Vendor.id, Vendor.name).where(
        Vendor.id.in_({v for v in (request.vendor_id, request.suggested_vendor_id) if v}))).all())
    return RequestDetail(
        **summary.model_dump(),
        justification=request.justification, cost_center=request.cost_center,
        category_id=request.category_id, requested_by=request.requested_by,
        assigned_buyer_id=request.assigned_buyer_id, vendor_id=request.vendor_id,
        vendor_name=vendors.get(request.vendor_id), suggested_vendor_id=request.suggested_vendor_id,
        suggested_vendor_name=vendors.get(request.suggested_vendor_id),
        completed_by_id=request.completed_by_id, approval_round=request.approval_round,
        # The PO itself is drafted into ERPNext in Step 13 (§8); until then "approved" means ready.
        ready_for_po=request.status == "approved",
        lines=[LineOut.model_validate(line) for line in service.request_lines(db, request)],
        current_steps=[StepOut(step=s.step, required_role=s.required_role, approver_id=s.approver_id,
                               approver_name=names.get(s.approver_id), decision=s.decision,
                               reason=s.reason, decided_at=s.decided_at) for s in steps],
        timeline=[TimelineEvent(seq=e.seq, action=e.action, actor_name=names.get(e.actor_id),
                                at=e.created_at, payload=e.payload) for e in events],
        allowed=_allowed(db, user, request, steps),
    )


def _commit_and_show(db: Session, user: User, request: PurchaseRequest) -> RequestDetail:
    db.commit()
    return _detail(db, user, request)


# --- Requests ------------------------------------------------------------------------------------

@router.get("/requests", response_model=list[RequestSummary])
def list_requests(user: CurrentUser, db: DbSession, scope: Scope = Query("all")) -> list[RequestSummary]:
    query = select(PurchaseRequest).where(PurchaseRequest.org_id == user.org_id)
    if scope == "mine" or user.role not in service.ORG_WIDE_VIEWERS:
        query = query.where(PurchaseRequest.requested_by == user.id)
    elif scope == "buyer_queue":
        query = query.where(PurchaseRequest.assigned_buyer_id == user.id,
                            PurchaseRequest.status == "with_buyer")
    elif scope == "admin_queue":
        query = query.where(PurchaseRequest.status == "submitted", PurchaseRequest.assigned_buyer_id.is_(None))
    elif scope == "approvals":
        query = query.where(PurchaseRequest.status == "in_approval")
    requests = list(db.scalars(query.order_by(PurchaseRequest.updated_at.desc())))
    if scope == "approvals":
        requests = [r for r in requests if service.next_step_for(db, user, r) is not None]
    return _summaries(db, requests)


@router.post("/requests", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(body: RequestCreate, user: CurrentUser, db: DbSession) -> RequestDetail:
    request = service.create_request(
        db, user, category_id=body.category_id, title=body.title, justification=body.justification,
        cost_center=body.cost_center, needed_by=body.needed_by, suggested_vendor_id=body.suggested_vendor_id,
        lines=[service.LineInput(**line.model_dump()) for line in body.lines])
    return _commit_and_show(db, user, request)


@router.get("/requests/{request_id}", response_model=RequestDetail)
def get_request(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RequestDetail:
    return _detail(db, user, service.load_request(db, user, request_id))


@router.patch("/requests/{request_id}", response_model=RequestDetail)
def edit_request(request_id: uuid.UUID, body: RequestEdit, user: CurrentUser, db: DbSession) -> RequestDetail:
    lines = [service.LineInput(**line.model_dump()) for line in body.lines] if body.lines is not None else None
    request = service.edit_request(
        db, user, request_id, title=body.title, justification=body.justification,
        cost_center=body.cost_center, needed_by=body.needed_by, category_id=body.category_id, lines=lines)
    return _commit_and_show(db, user, request)


@router.post("/requests/{request_id}/submit", response_model=RequestDetail)
def submit_request(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RequestDetail:
    return _commit_and_show(db, user, service.submit_request(db, user, request_id))


@router.post("/requests/{request_id}/assign", response_model=RequestDetail)
def assign_buyer(request_id: uuid.UUID, body: AssignBuyer, user: CurrentUser, db: DbSession) -> RequestDetail:
    return _commit_and_show(db, user, service.assign_buyer(db, user, request_id, body.buyer_id))


@router.patch("/requests/{request_id}/buyer", response_model=RequestDetail)
def buyer_update(request_id: uuid.UUID, body: BuyerUpdate, user: CurrentUser, db: DbSession) -> RequestDetail:
    request = service.buyer_update(
        db, user, request_id, vendor_id=body.vendor_id,
        lines=[service.BuyerLineInput(**line.model_dump()) for line in body.lines])
    return _commit_and_show(db, user, request)


@router.post("/requests/{request_id}/send-for-approval", response_model=RequestDetail)
def send_for_approval(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RequestDetail:
    return _commit_and_show(db, user, service.send_for_approval(db, user, request_id))


@router.post("/requests/{request_id}/approvals/{step}/decision", response_model=RequestDetail)
def decide(request_id: uuid.UUID, step: int, body: DecisionIn, user: CurrentUser, db: DbSession) -> RequestDetail:
    return _commit_and_show(db, user, service.decide(db, user, request_id, step, body.decision, body.reason))
