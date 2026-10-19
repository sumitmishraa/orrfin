"""Budgets per cost centre and financial-year quarter (BUILD_PLAN v2.4 change 30; PROMPTS Step 22).

Zip checks a request against its budget before approval. Orrfin does the same but only warns:
a budget never blocks a request, because the approvers, not a number, decide.

- committed = requests in approval or approved (incl. PO drafted/open) for that cost centre,
  counted in the quarter the request was raised (India time);
- invoiced  = approved invoices whose PO came from such a request.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Invalid
from app.models import Budget, Invoice, PurchaseOrder, PurchaseRequest, User
from app.modules.audit.service import record_event
from app.modules.invoices.validation import fiscal_year

IST = ZoneInfo("Asia/Kolkata")
ZERO = Decimal("0")
CENT = Decimal("0.01")
COMMITTED_STATUSES = ("in_approval", "approved", "po_drafted", "po_open")
EDITOR_ROLES = ("finance", "admin")
_QUARTER_FIRST_MONTH = {1: 4, 2: 7, 3: 10, 4: 1}


def rupees(amount: Decimal) -> str:
    """₹ with Indian digit grouping: 240000 → "₹2,40,000.00" (what an Indian finance team reads)."""
    sign = "-" if amount < 0 else ""
    whole, paise = f"{abs(amount):.2f}".split(".")
    last3, rest = whole[-3:], whole[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f"{sign}₹" + ",".join(groups + [last3]) + "." + paise


def quarter_of(day: date) -> tuple[str, int]:
    """Financial year and quarter: Apr–Jun = Q1 … Jan–Mar = Q4. 18 Oct 2026 → ("2026-27", 3)."""
    return fiscal_year(day), (day.month - 4) % 12 // 3 + 1


def quarter_bounds(fy: str, quarter: int) -> tuple[datetime, datetime]:
    """[start, end) of a quarter as UTC instants, counted in India time."""
    start_year = int(fy[:4]) + (1 if quarter == 4 else 0)
    month = _QUARTER_FIRST_MONTH[quarter]
    start = datetime(start_year, month, 1, tzinfo=IST)
    end = datetime(start_year + (1 if month == 10 else 0), 1 if month == 10 else month + 3, 1, tzinfo=IST)
    return start.astimezone(UTC), end.astimezone(UTC)


def today_ist() -> date:
    return datetime.now(IST).date()


def _committed(db: Session, org_id: uuid.UUID, cost_center: str, fy: str, quarter: int,
               exclude_request_id: uuid.UUID | None = None) -> Decimal:
    start, end = quarter_bounds(fy, quarter)
    query = select(func.coalesce(func.sum(PurchaseRequest.amount), 0)).where(
        PurchaseRequest.org_id == org_id, func.upper(PurchaseRequest.cost_center) == cost_center.upper(),
        PurchaseRequest.status.in_(COMMITTED_STATUSES),
        PurchaseRequest.created_at >= start, PurchaseRequest.created_at < end)
    if exclude_request_id is not None:
        query = query.where(PurchaseRequest.id != exclude_request_id)
    return Decimal(db.scalar(query))


def _invoiced(db: Session, org_id: uuid.UUID, cost_center: str, fy: str, quarter: int) -> Decimal:
    start, end = quarter_bounds(fy, quarter)
    return Decimal(db.scalar(
        select(func.coalesce(func.sum(Invoice.total), 0))
        .join(PurchaseOrder, PurchaseOrder.id == Invoice.po_id)
        .join(PurchaseRequest, PurchaseRequest.id == PurchaseOrder.request_id)
        .where(Invoice.org_id == org_id, Invoice.status == "approved",
               func.upper(PurchaseRequest.cost_center) == cost_center.upper(),
               PurchaseRequest.created_at >= start, PurchaseRequest.created_at < end)))


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole <= 0:
        return None
    return (part * 100 / whole).quantize(Decimal("0.1"), ROUND_HALF_UP)


def find(db: Session, org_id: uuid.UUID, cost_center: str, fy: str, quarter: int) -> Budget | None:
    return db.scalar(select(Budget).where(Budget.org_id == org_id, Budget.cost_center == cost_center,
                                          Budget.fiscal_year == fy, Budget.quarter == quarter))


def check(db: Session, org_id: uuid.UUID, cost_center: str, amount: Decimal, *, day: date | None = None,
          request_id: uuid.UUID | None = None) -> dict[str, Any] | None:
    """What this request would do to its cost centre's budget. None when no budget is set.

    `request_id` leaves the request itself out of "already committed", so the answer is the same
    before and after it enters approval.
    """
    cost_center = cost_center.strip().upper()
    if not cost_center:
        return None
    fy, quarter = quarter_of(day or today_ist())
    budget = find(db, org_id, cost_center, fy, quarter)
    if budget is None:
        return None
    committed = _committed(db, org_id, cost_center, fy, quarter, exclude_request_id=request_id)
    after = committed + amount
    over = after > budget.amount
    pct_after = _pct(after, budget.amount)
    message = (f"{cost_center} {fy} Q{quarter}: {rupees(committed)} of {rupees(budget.amount)} already committed; "
               f"this request takes it to {pct_after}%." if pct_after is not None else
               f"{cost_center} {fy} Q{quarter} has a zero budget.")
    if over:
        message += f" That is {rupees(after - budget.amount)} over budget. Approvers will see this warning."
    return {"cost_center": cost_center, "fiscal_year": fy, "quarter": quarter, "budget": budget.amount,
            "committed": committed, "after": after, "pct_after": pct_after, "over": over, "message": message}


def status_rows(db: Session, org_id: uuid.UUID, fy: str, quarter: int) -> list[dict[str, Any]]:
    rows = []
    for budget in db.scalars(select(Budget).where(Budget.org_id == org_id, Budget.fiscal_year == fy,
                                                  Budget.quarter == quarter).order_by(Budget.cost_center)):
        committed = _committed(db, org_id, budget.cost_center, fy, quarter)
        rows.append({"id": budget.id, "cost_center": budget.cost_center, "fiscal_year": fy, "quarter": quarter,
                     "budget": budget.amount, "committed": committed,
                     "invoiced": _invoiced(db, org_id, budget.cost_center, fy, quarter),
                     "remaining": budget.amount - committed, "pct_used": _pct(committed, budget.amount),
                     "over": committed > budget.amount})
    return rows


def set_budget(db: Session, user: User, cost_center: str, fy: str, quarter: int, amount: Decimal) -> Budget:
    cost_center = cost_center.strip().upper()
    if not cost_center:
        raise Invalid("Give a cost centre.")
    if not (len(fy) == 7 and fy[4] == "-" and fy[:4].isdigit() and fy[5:] == str(int(fy[:4]) + 1)[2:]):
        raise Invalid('Financial year must look like "2026-27".')
    if quarter not in (1, 2, 3, 4):
        raise Invalid("Quarter must be 1, 2, 3 or 4.")
    if amount < 0 or amount != amount.quantize(CENT):
        raise Invalid("Budget must be zero or more, in rupees and paise.")
    budget = db.scalar(select(Budget).where(Budget.org_id == user.org_id, Budget.cost_center == cost_center,
                                            Budget.fiscal_year == fy, Budget.quarter == quarter).with_for_update())
    old = budget.amount if budget else None
    if budget is None:
        budget = Budget(org_id=user.org_id, cost_center=cost_center, fiscal_year=fy, quarter=quarter, amount=amount)
        db.add(budget)
        db.flush()
    else:
        budget.amount = amount
    record_event(db, org_id=user.org_id, entity_type="budget", entity_id=budget.id, actor_id=user.id,
                 action="budget_set", payload={"cost_center": cost_center, "fiscal_year": fy, "quarter": quarter,
                                               "old": old, "new": amount})
    return budget
