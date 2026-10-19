"""Control dashboard numbers (BUILD_PLAN v2.3 change 23; PROMPTS Step 21).

Read-only and deterministic: plain SQL over Orrfin's own tables, no AI. Every query is
filtered by the caller's org, and by role the same way the pages are:
- requesters see request numbers for their own requests only, and no invoice or spend data;
- buyers see requests they own as buyer (assigned, or their category) plus org-wide invoices;
- approvers, finance and admins see the whole org.

Money stays Decimal; durations are hours as Decimal with one decimal place.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select, true
from sqlalchemy.orm import Session

from app.models import (
    Category,
    ErpOutbox,
    Extraction,
    FieldEdit,
    Invoice,
    MatchResult,
    PurchaseRequest,
    RequestApproval,
    User,
)

Period = Literal["month", "quarter", "all"]
IST = ZoneInfo("Asia/Kolkata")
ZERO = Decimal("0")
TENTH = Decimal("0.1")

OPEN_REQUEST_STATUSES = ("submitted", "with_buyer", "in_approval", "returned")
# A request counts as spend once its approval chain finished.
APPROVED_REQUEST_STATUSES = ("approved", "po_drafted", "po_open")
# "On hold" = money that Orrfin stopped and a person has not yet released.
ON_HOLD_INVOICE_STATUSES = ("exception", "correction_requested")
REQUEST_ONLY_ROLES = ("requester",)


@dataclass(frozen=True)
class Scope:
    """Who is asking, so every query can be narrowed the same way."""
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str


def period_start(period: Period, today: date | None = None) -> datetime | None:
    """Start of the period in UTC, counted in India time. Indian financial-year quarters
    (Apr–Jun, Jul–Sep, Oct–Dec, Jan–Mar) start in the same months as calendar quarters."""
    if period == "all":
        return None
    today = today or datetime.now(IST).date()
    month = today.month if period == "month" else today.month - (today.month - 1) % 3
    return datetime(today.year, month, 1, tzinfo=IST).astimezone(UTC)


def _hours(delta: timedelta) -> Decimal:
    return (Decimal(delta.total_seconds()) / Decimal(3600)).quantize(TENTH, ROUND_HALF_UP)


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, ZERO) / len(values)).quantize(TENTH, ROUND_HALF_UP)


def request_filter(query: Select, scope: Scope) -> Select:
    """Narrow a query that includes PurchaseRequest to the requests this user may see."""
    query = query.where(PurchaseRequest.org_id == scope.org_id)
    if scope.role == "requester":
        return query.where(PurchaseRequest.requested_by == scope.user_id)
    if scope.role == "buyer":
        own_categories = select(Category.id).where(Category.org_id == scope.org_id,
                                                   Category.buyer_id == scope.user_id)
        return query.where(or_(PurchaseRequest.assigned_buyer_id == scope.user_id,
                               PurchaseRequest.category_id.in_(own_categories)))
    return query


def _since(column, start: datetime | None):
    return column >= start if start is not None else true()


# --- Requests and approvals ------------------------------------------------------------------------

def _request_numbers(db: Session, scope: Scope, start: datetime | None) -> dict[str, Any]:
    open_counts = dict(db.execute(request_filter(
        select(PurchaseRequest.status, func.count()), scope)
        .where(PurchaseRequest.status.in_(OPEN_REQUEST_STATUSES))
        .group_by(PurchaseRequest.status)).all())

    # The step each in-approval request waits on: the first undecided step of its current round.
    pending = db.execute(request_filter(
        select(RequestApproval.required_role, RequestApproval.created_at, PurchaseRequest.id), scope)
        .join(PurchaseRequest, PurchaseRequest.id == RequestApproval.request_id)
        .where(PurchaseRequest.status == "in_approval",
               RequestApproval.round == PurchaseRequest.approval_round,
               RequestApproval.decision.is_(None))
        .order_by(PurchaseRequest.id, RequestApproval.step)).all()
    waiting: dict[str, dict[str, Any]] = {}
    seen: set[uuid.UUID] = set()
    now = datetime.now(UTC)
    for role, created_at, request_id in pending:
        if request_id in seen:
            continue
        seen.add(request_id)
        entry = waiting.setdefault(role, {"step": role, "count": 0, "oldest_hours": ZERO})
        entry["count"] += 1
        entry["oldest_hours"] = max(entry["oldest_hours"], _hours(now - created_at))

    rows = db.execute(request_filter(select(RequestApproval, PurchaseRequest.status), scope)
                      .join(PurchaseRequest, PurchaseRequest.id == RequestApproval.request_id)
                      .where(RequestApproval.round == PurchaseRequest.approval_round)
                      .order_by(RequestApproval.request_id, RequestApproval.step)).all()
    by_request: dict[uuid.UUID, list[RequestApproval]] = defaultdict(list)
    statuses: dict[uuid.UUID, str] = {}
    for step, status in rows:
        by_request[step.request_id].append(step)
        statuses[step.request_id] = status

    cycle_hours: list[Decimal] = []
    approver_waits: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
    for request_id, steps in by_request.items():
        previous_done: datetime | None = None
        for step in steps:
            # A step becomes actionable when the chain starts (step 1) or the step before it ends.
            available = previous_done or step.created_at
            if step.decided_at is not None:
                if step.approver_id and (start is None or step.decided_at >= start):
                    approver_waits[step.approver_id].append(_hours(step.decided_at - available))
                previous_done = step.decided_at
        if statuses[request_id] in APPROVED_REQUEST_STATUSES and all(s.decided_at for s in steps):
            finished = max(s.decided_at for s in steps)
            if start is None or finished >= start:
                cycle_hours.append(_hours(finished - min(s.created_at for s in steps)))

    names = _names(db, set(approver_waits))
    slowest = sorted(({"approver": names.get(a, "Unknown"), "decisions": len(w), "average_hours": _mean(w)}
                      for a, w in approver_waits.items()),
                     key=lambda r: r["average_hours"], reverse=True)[:5]

    return {
        "open_by_status": {s: open_counts.get(s, 0) for s in OPEN_REQUEST_STATUSES},
        "open_total": sum(open_counts.values()),
        "waiting_by_step": sorted(waiting.values(), key=lambda w: w["count"], reverse=True),
        "approval_hours_average": _mean(cycle_hours),
        "approval_hours_median": (Decimal(median(cycle_hours)).quantize(TENTH, ROUND_HALF_UP)
                                  if cycle_hours else None),
        "approved_count": len(cycle_hours),
        "slowest_approvers": slowest,
    }


def _names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


# --- Invoices --------------------------------------------------------------------------------------

def latest_matches(db: Session, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, MatchResult]:
    latest: dict[uuid.UUID, MatchResult] = {}
    if not invoice_ids:
        return latest
    for match in db.scalars(select(MatchResult).where(MatchResult.invoice_id.in_(invoice_ids))
                            .order_by(MatchResult.created_at)):
        latest[match.invoice_id] = match
    return latest


def _invoice_numbers(db: Session, scope: Scope, start: datetime | None) -> dict[str, Any]:
    invoices = db.scalars(select(Invoice).where(Invoice.org_id == scope.org_id,
                                                _since(Invoice.created_at, start))).all()
    ids = [i.id for i in invoices]
    latest = latest_matches(db, ids)

    first_outcome: dict[uuid.UUID, str] = {}
    if ids:
        for invoice_id, outcome in db.execute(select(MatchResult.invoice_id, MatchResult.outcome)
                                              .where(MatchResult.invoice_id.in_(ids))
                                              .order_by(MatchResult.created_at)).all():
            first_outcome.setdefault(invoice_id, outcome)
    matched_first_time = sum(1 for o in first_outcome.values() if o == "matched")

    on_hold = [i for i in invoices if i.status in ON_HOLD_INVOICE_STATUSES]
    at_risk = sum((latest[i.id].amount_at_risk for i in on_hold if i.id in latest), ZERO)
    exceptions_by_code: Counter[str] = Counter()
    for invoice in on_hold:
        match = latest.get(invoice.id)
        if match is None:
            continue
        for rule in match.rule_results:
            if rule.get("status") == "fail":
                exceptions_by_code[rule.get("code", "UNKNOWN")] += 1

    edits = edited_invoices = read_by_ai = 0
    if ids:
        edits = db.scalar(select(func.count()).select_from(FieldEdit).where(FieldEdit.invoice_id.in_(ids)))
        edited_invoices = db.scalar(select(func.count(func.distinct(FieldEdit.invoice_id)))
                                    .where(FieldEdit.invoice_id.in_(ids)))
        read_by_ai = db.scalar(select(func.count(func.distinct(Extraction.invoice_id)))
                               .where(Extraction.invoice_id.in_(ids)))

    return {
        "total": len(invoices),
        "by_status": dict(Counter(i.status for i in invoices)),
        "on_hold_count": len(on_hold),
        "on_hold_amount_at_risk": at_risk,
        "rejected_total": sum((i.total or ZERO for i in invoices if i.status == "rejected"), ZERO),
        "first_pass_match_rate": (Decimal(matched_first_time * 100) / len(first_outcome)).quantize(TENTH)
                                 if first_outcome else None,
        "matched_first_time": matched_first_time,
        "match_attempted": len(first_outcome),
        "exceptions_by_code": [{"code": c, "count": n} for c, n in exceptions_by_code.most_common()],
        "extraction": {
            "read_by_ai": read_by_ai,
            "manual_entry": sum(1 for i in invoices if i.extraction_error),
            "invoices_corrected": edited_invoices,
            "field_edits": edits,
        },
    }


# --- Spend and ERP ---------------------------------------------------------------------------------

def _ranked(values: dict[str, Decimal], limit: int | None = None) -> list[dict[str, Any]]:
    rows = sorted(({"name": k, "amount": v} for k, v in values.items()),
                  key=lambda r: (-r["amount"], r["name"]))
    return rows[:limit] if limit else rows


def _spend(db: Session, scope: Scope, start: datetime | None) -> dict[str, Any]:
    approved = request_filter(select(PurchaseRequest), scope).where(
        PurchaseRequest.status.in_(APPROVED_REQUEST_STATUSES), _since(PurchaseRequest.created_at, start))
    categories = dict(db.execute(select(Category.id, Category.name)
                                 .where(Category.org_id == scope.org_id)).all())
    by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_cost_center: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for request in db.scalars(approved):
        by_category[categories.get(request.category_id, "Other")] += request.amount
        by_cost_center[request.cost_center or "Not set"] += request.amount

    by_vendor: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for name, total in db.execute(select(Invoice.vendor_name, Invoice.total).where(
            Invoice.org_id == scope.org_id, Invoice.status == "approved",
            _since(Invoice.created_at, start))).all():
        by_vendor[name or "Unknown vendor"] += total or ZERO

    return {
        "approved_requests_total": sum(by_category.values(), ZERO),
        "by_category": _ranked(by_category),
        "by_cost_center": _ranked(by_cost_center),
        "approved_invoices_total": sum(by_vendor.values(), ZERO),
        "top_vendors": _ranked(by_vendor, 5),
    }


def _erp_drafts(db: Session, scope: Scope, start: datetime | None) -> list[dict[str, Any]]:
    rows = db.execute(select(ErpOutbox.doc_type, ErpOutbox.state, func.count())
                      .where(ErpOutbox.org_id == scope.org_id, _since(ErpOutbox.created_at, start))
                      .group_by(ErpOutbox.doc_type, ErpOutbox.state)).all()
    return [{"doc_type": d, "state": s, "count": n} for d, s, n in sorted(rows)]


# Later steps (budgets, payments, GST, close) register extra dashboard sections here,
# so this module never imports them: each section is fn(db, scope, start) -> dict | None.
SECTION_PROVIDERS: dict[str, Any] = {}


def summary(db: Session, scope: Scope, period: Period) -> dict[str, Any]:
    start = period_start(period)
    result: dict[str, Any] = {
        "period": period,
        "period_start": start,
        "role": scope.role,
        "requests": _request_numbers(db, scope, start),
        "invoices": None,
        "spend": None,
        "erp_drafts": None,
        "sections": {},
    }
    if scope.role not in REQUEST_ONLY_ROLES:
        result["invoices"] = _invoice_numbers(db, scope, start)
        result["spend"] = _spend(db, scope, start)
        result["erp_drafts"] = _erp_drafts(db, scope, start)
    for name, provider in SECTION_PROVIDERS.items():
        section = provider(db, scope, start)
        if section is not None:
            result["sections"][name] = section
    return result
