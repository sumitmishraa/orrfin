"""HTTP routes for workflow automations and budgets (BUILD_PLAN v2.4 changes 29–30; PROMPTS Step 22).

Importing this module also plugs two sections into other pages, without those modules
importing this one: the invoice page's questions (DETAIL_EXTENSIONS) and the dashboard's
overdue-approvals and budget sections (insights SECTION_PROVIDERS).
"""

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.models import Invoice, User
from app.modules.audit.service import to_jsonable
from app.modules.insights.service import SECTION_PROVIDERS
from app.modules.invoices.router import DETAIL_EXTENSIONS, build_detail
from app.modules.invoices.schemas import InvoiceDetail
from app.modules.procurement import service as procurement
from app.modules.workflows import budgets, service

router = APIRouter(tags=["workflows"])


def _json(value: Any) -> JSONResponse:
    return JSONResponse(to_jsonable(value))


# --- My tasks and reminders --------------------------------------------------------------------------

@router.get("/tasks")
def my_tasks(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.my_tasks(db, user))


def _reminder_view(db: Session, user: User, request) -> dict[str, Any]:
    status = service.approval_status(db, request)
    involved = user.id in (request.requested_by, request.assigned_buyer_id, request.completed_by_id)
    return {"status": status,
            "can_nudge": bool(status and status["overdue"] and (involved or user.role in service.NUDGE_ROLES))}


@router.get("/requests/{request_id}/reminders")
def reminders(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(_reminder_view(db, user, procurement.load_request(db, user, request_id)))


@router.post("/requests/{request_id}/nudge")
def nudge(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    request = service.nudge(db, user, request_id)
    db.commit()
    return _json(_reminder_view(db, user, request))


# --- Exception tasks (questions on a held invoice) ---------------------------------------------------

class QuestionIn(BaseModel):
    assigned_to: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


def _add_tasks(db: Session, user: User, invoice: Invoice, detail: InvoiceDetail) -> None:
    detail.exception_tasks = to_jsonable(service.task_view(db, user, invoice))


DETAIL_EXTENSIONS.append(_add_tasks)


@router.post("/invoices/{invoice_id}/questions", response_model=InvoiceDetail)
def ask(invoice_id: uuid.UUID, body: QuestionIn, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    task = service.ask(db, user, invoice_id, body.assigned_to, body.question)
    db.commit()
    return build_detail(db, user, db.get(Invoice, task.invoice_id))


@router.post("/exception-tasks/{task_id}/answer", response_model=InvoiceDetail)
def answer(task_id: uuid.UUID, body: AnswerIn, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    task = service.answer(db, user, task_id, body.answer)
    db.commit()
    return build_detail(db, user, db.get(Invoice, task.invoice_id))


# --- Settings ----------------------------------------------------------------------------------------

class WorkflowSettingsIn(BaseModel):
    approval_sla_hours: int = Field(ge=1, le=720)


@router.get("/settings/workflow")
def workflow_settings(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json({"approval_sla_hours": service.sla_hours(db, user.org_id), "can_edit": user.role == "admin"})


@router.put("/settings/workflow", dependencies=[Depends(require_roles("admin"))])
def set_workflow_settings(body: WorkflowSettingsIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.set_sla_hours(db, user, body.approval_sla_hours)
    db.commit()
    return _json({"approval_sla_hours": body.approval_sla_hours, "can_edit": True})


# --- Budgets -----------------------------------------------------------------------------------------

class BudgetIn(BaseModel):
    cost_center: str = Field(min_length=1, max_length=60)
    fiscal_year: str = Field(min_length=7, max_length=7)
    quarter: int = Field(ge=1, le=4)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


def _period(fiscal_year: str | None, quarter: int | None) -> tuple[str, int]:
    current_fy, current_q = budgets.quarter_of(budgets.today_ist())
    return fiscal_year or current_fy, quarter or current_q


@router.get("/budgets", dependencies=[Depends(require_roles("buyer", "approver", "finance", "admin"))])
def list_budgets(user: CurrentUser, db: DbSession, fiscal_year: str | None = None,
                 quarter: int | None = Query(None, ge=1, le=4)) -> JSONResponse:
    fy, q = _period(fiscal_year, quarter)
    return _json({"fiscal_year": fy, "quarter": q, "can_edit": user.role in budgets.EDITOR_ROLES,
                  "rows": budgets.status_rows(db, user.org_id, fy, q)})


@router.put("/budgets", dependencies=[Depends(require_roles(*budgets.EDITOR_ROLES))])
def set_budget(body: BudgetIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    budgets.set_budget(db, user, body.cost_center, body.fiscal_year, body.quarter, body.amount)
    db.commit()
    return _json({"fiscal_year": body.fiscal_year, "quarter": body.quarter, "can_edit": True,
                  "rows": budgets.status_rows(db, user.org_id, body.fiscal_year, body.quarter)})


@router.get("/budgets/check")
def check_budget(user: CurrentUser, db: DbSession, cost_center: str = Query("", max_length=60),
                 amount: Decimal = Query(Decimal("0"), ge=0), request_id: uuid.UUID | None = None) -> JSONResponse:
    """Budget effect of a request (the requester's form and the request page). Warning only."""
    if request_id is not None:
        request = procurement.load_request(db, user, request_id)
        cost_center, amount = request.cost_center, request.amount
    return _json(budgets.check(db, user.org_id, cost_center.strip().upper(), amount, request_id=request_id))


# --- Dashboard sections ------------------------------------------------------------------------------

def _budget_section(db: Session, scope: Any, start: Any) -> dict[str, Any] | None:
    if scope.role == "requester":
        return None
    fy, q = budgets.quarter_of(budgets.today_ist())
    rows = budgets.status_rows(db, scope.org_id, fy, q)
    return {"fiscal_year": fy, "quarter": q, "rows": rows} if rows else None


SECTION_PROVIDERS["overdue_approvals"] = service.overdue_section
SECTION_PROVIDERS["budgets"] = _budget_section
