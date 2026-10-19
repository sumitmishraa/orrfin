"""Workflow automations from the Zip guide (BUILD_PLAN v2.4 change 29; PROMPTS Step 22).

- My tasks: everything waiting on the logged-in user, derived live from the records (no task
  table to drift out of date), with age and an "overdue" flag past the org's approval SLA.
- Nudge: a reminder on an overdue approval step, recorded in the request's audit trail.
- WhatsApp preview: the message an approver *would* receive. Built by a template, never sent;
  the link opens the normal page, where login and every server rule still apply.
- Exception tasks: a reviewer holds an invoice and asks a named person a question. While it is
  open the invoice cannot be approved, and the person asked can never approve it
  (enforced in review/service.py, which owns invoice decisions).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import (
    AuditEvent,
    Document,
    ExceptionTask,
    Invoice,
    OrgSettings,
    PurchaseOrder,
    PurchaseRequest,
    RequestApproval,
    User,
)
from app.modules.audit.service import record_event
from app.modules.invoices.service import load_invoice
from app.modules.procurement import service as procurement
from app.modules.workflows.budgets import rupees

DEFAULT_SLA_HOURS = 48
NUDGE_COOLDOWN = timedelta(hours=12)
ASKER_ROLES = ("finance", "admin")
ASKABLE_STATUSES = ("exception", "matched")
INVOICE_DECIDER_ROLES = ("finance", "admin")
ROLE_WORDS = {"manager": "Requester's manager", "approver": "Approver", "finance": "Finance", "admin": "Admin"}


# --- Settings ----------------------------------------------------------------------------------------

def sla_hours(db: Session, org_id: uuid.UUID) -> int:
    row = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    return row.approval_sla_hours if row else DEFAULT_SLA_HOURS


def set_sla_hours(db: Session, user: User, hours: int) -> OrgSettings:
    if not 1 <= hours <= 720:
        raise Invalid("The approval time limit must be between 1 and 720 hours.")
    row = db.scalar(select(OrgSettings).where(OrgSettings.org_id == user.org_id).with_for_update())
    old = row.approval_sla_hours if row else DEFAULT_SLA_HOURS
    if row is None:
        row = OrgSettings(org_id=user.org_id, approval_sla_hours=hours)
        db.add(row)
        db.flush()
    else:
        row.approval_sla_hours = hours
    record_event(db, org_id=user.org_id, entity_type="org_settings", entity_id=row.id, actor_id=user.id,
                 action="approval_sla_changed", payload={"old_hours": old, "new_hours": hours})
    return row


# --- Approval steps: age, overdue, nudges -----------------------------------------------------------

def _hours(delta: timedelta) -> Decimal:
    return (Decimal(delta.total_seconds()) / 3600).quantize(Decimal("0.1"), ROUND_HALF_UP)


def pending_step(steps: list[RequestApproval]) -> tuple[RequestApproval | None, datetime | None]:
    """The step the chain waits on, and when it became actionable (chain start or the previous decision)."""
    previous_done: datetime | None = None
    for step in sorted(steps, key=lambda s: s.step):
        if step.decision is None:
            return step, previous_done or step.created_at
        previous_done = step.decided_at
    return None, None


def step_waiting_on(db: Session, request: PurchaseRequest, step: RequestApproval) -> str:
    """Who the step waits on, in words: a named person where the chain fixes one, else the role."""
    if step.required_role == procurement.CATEGORY_STEP:
        named = db.get(User, step.designated_approver_id)
        return f"{step.step_label} by {named.full_name if named else 'its reviewer'}"
    if step.required_role == "manager":
        requester = db.get(User, request.requested_by)
        manager = db.get(User, requester.manager_id) if requester and requester.manager_id else None
        return f"Requester's manager ({manager.full_name})" if manager else "Requester's manager"
    return ROLE_WORDS.get(step.required_role, step.required_role)


def _nudges(db: Session, request: PurchaseRequest, step: RequestApproval) -> list[dict[str, Any]]:
    events = db.execute(select(AuditEvent, User.full_name).join(User, User.id == AuditEvent.actor_id)
                        .where(AuditEvent.entity_id == request.id, AuditEvent.action == "nudged")
                        .order_by(AuditEvent.seq)).all()
    return [{"by": name, "at": e.created_at} for e, name in events
            if e.payload.get("round") == request.approval_round and e.payload.get("step") == step.step]


def approval_status(db: Session, request: PurchaseRequest, now: datetime | None = None) -> dict[str, Any] | None:
    """Age and overdue state of the step a request waits on, or None if it is not in approval."""
    if request.status != "in_approval":
        return None
    step, since = pending_step(procurement.current_steps(db, request))
    if step is None:
        return None
    sla = sla_hours(db, request.org_id)
    age = _hours((now or datetime.now(UTC)) - since)
    return {"step": step.step, "waiting_on": step_waiting_on(db, request, step), "since": since,
            "age_hours": age, "sla_hours": sla, "overdue": age > sla, "nudges": _nudges(db, request, step)}


NUDGE_ROLES = ("finance", "admin")


def nudge(db: Session, user: User, request_id: uuid.UUID) -> PurchaseRequest:
    request = procurement.load_request(db, user, request_id, lock=True)
    status = approval_status(db, request)
    if status is None:
        raise Conflict("This request is not waiting for an approval.")
    involved = user.id in (request.requested_by, request.assigned_buyer_id, request.completed_by_id)
    if not involved and user.role not in NUDGE_ROLES:
        raise Forbidden("Only the requester, the buyer, finance or an admin can send a reminder.")
    if not status["overdue"]:
        raise Conflict(f"Not overdue yet: it has waited {status['age_hours']} h of the "
                       f"{status['sla_hours']} h allowed.")
    last = status["nudges"][-1]["at"] if status["nudges"] else None
    if last and datetime.now(UTC) - last < NUDGE_COOLDOWN:
        raise Conflict("A reminder was already sent in the last 12 hours.")
    record_event(db, org_id=request.org_id, entity_type="purchase_request", entity_id=request.id, actor_id=user.id,
                 action="nudged", payload={"round": request.approval_round, "step": status["step"],
                                           "waiting_on": status["waiting_on"], "age_hours": status["age_hours"]})
    return request


# --- WhatsApp preview (nothing is ever sent) ---------------------------------------------------------

def whatsapp_text(kind: str, lines: list[str], path: str) -> str:
    """A WhatsApp-style message. The link is a path; the page adds its own origin."""
    title = {"approval": "Approval needed", "exception_task": "Question about an invoice",
             "answer": "Your question was answered", "invoice": "Invoice waiting for a decision",
             "buyer": "Request to complete", "returned": "Request returned to you"}.get(kind, "Task")
    return "\n".join([f"*Orrfin* · {title}", *lines, f"Open: {{origin}}{path}",
                      "_You will be asked to log in. Orrfin never approves from chat._"])


# --- My tasks ----------------------------------------------------------------------------------------

def _task(kind: str, entity_id: uuid.UUID, title: str, detail: str, path: str, since: datetime | None,
          *, overdue: bool = False, nudges: list | None = None, preview_lines: list[str] | None = None) -> dict:
    return {"kind": kind, "id": entity_id, "title": title, "detail": detail, "href": path,
            "since": since, "age_hours": _hours(datetime.now(UTC) - since) if since else None,
            "overdue": overdue, "nudges": nudges or [],
            "whatsapp": whatsapp_text(kind, preview_lines or [title, detail], path)}


def my_tasks(db: Session, user: User) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    number = procurement_number

    for request in db.scalars(select(PurchaseRequest).where(PurchaseRequest.org_id == user.org_id,
                                                            PurchaseRequest.status == "in_approval")):
        if procurement.next_step_for(db, user, request) is None:
            continue
        status = approval_status(db, request)
        requester = db.get(User, request.requested_by)
        title = f"{number(request.number)} · {request.title}"
        detail = f"{rupees(request.amount)} · step {status['step']}: {status['waiting_on']}"
        tasks.append(_task("approval", request.id, title, detail, f"/requests/{request.id}", status["since"],
                           overdue=status["overdue"], nudges=status["nudges"],
                           preview_lines=[title, f"{rupees(request.amount)} · requested by {requester.full_name}",
                                          f"Step {status['step']}: {status['waiting_on']}",
                                          f"Waiting {status['age_hours']} h"
                                          + (" · *overdue*" if status["overdue"] else "")]))

    if user.role == "buyer":
        for request in db.scalars(select(PurchaseRequest).where(
                PurchaseRequest.org_id == user.org_id, PurchaseRequest.assigned_buyer_id == user.id,
                PurchaseRequest.status == "with_buyer")):
            tasks.append(_task("buyer", request.id, f"{number(request.number)} · {request.title}",
                               f"{rupees(request.amount)} · choose the vendor and item codes",
                               f"/requests/{request.id}", request.updated_at))

    for request in db.scalars(select(PurchaseRequest).where(
            PurchaseRequest.org_id == user.org_id, PurchaseRequest.requested_by == user.id,
            PurchaseRequest.status == "returned")):
        tasks.append(_task("returned", request.id, f"{number(request.number)} · {request.title}",
                           "Returned to you for changes", f"/requests/{request.id}", request.updated_at))

    for task, invoice in db.execute(select(ExceptionTask, Invoice).join(Invoice, Invoice.id == ExceptionTask.invoice_id)
                                    .where(ExceptionTask.org_id == user.org_id, ExceptionTask.assigned_to == user.id,
                                           ExceptionTask.status == "open")).all():
        asker = db.get(User, task.asked_by)
        tasks.append(_task("exception_task", task.id, f"Invoice {invoice.invoice_no or ''} · {invoice.vendor_name or ''}",
                           f"{asker.full_name} asks: {task.question}", f"/invoices/{invoice.id}", task.created_at))

    for task, invoice in db.execute(select(ExceptionTask, Invoice).join(Invoice, Invoice.id == ExceptionTask.invoice_id)
                                    .where(ExceptionTask.org_id == user.org_id, ExceptionTask.asked_by == user.id,
                                           ExceptionTask.status == "answered")).all():
        tasks.append(_task("answer", task.id, f"Invoice {invoice.invoice_no or ''} · {invoice.vendor_name or ''}",
                           f"Answer: {task.answer}", f"/invoices/{invoice.id}", task.answered_at))

    if user.role in INVOICE_DECIDER_ROLES:
        sla = sla_hours(db, user.org_id)
        for invoice in db.scalars(select(Invoice).where(Invoice.org_id == user.org_id,
                                                        Invoice.status.in_(ASKABLE_STATUSES))):
            uploader = db.scalar(select(Document.uploaded_by).where(Document.id == invoice.document_id))
            if uploader == user.id:
                continue  # they cannot approve it, so it is someone else's task
            label = "Exception: decide with a reason" if invoice.status == "exception" else "Matched: ready to approve"
            task = _task("invoice", invoice.id, f"Invoice {invoice.invoice_no or ''} · {invoice.vendor_name or ''}",
                         f"{rupees(invoice.total or Decimal('0'))} · {label}", f"/invoices/{invoice.id}",
                         invoice.updated_at)
            task["overdue"] = task["age_hours"] is not None and task["age_hours"] > sla
            tasks.append(task)

    tasks.sort(key=lambda t: (not t["overdue"], -(t["age_hours"] or 0)))
    return tasks


def procurement_number(n: int) -> str:
    return f"PR-{n:04d}"


def overdue_section(db: Session, scope: Any, start: Any) -> dict[str, Any] | None:
    """Dashboard section (insights SECTION_PROVIDERS): approval steps waiting past the SLA."""
    if scope.role == "requester":
        return None
    sla = sla_hours(db, scope.org_id)
    rows = []
    for request in db.scalars(select(PurchaseRequest).where(PurchaseRequest.org_id == scope.org_id,
                                                            PurchaseRequest.status == "in_approval")):
        status = approval_status(db, request)
        if status and status["overdue"]:
            rows.append({"request_id": request.id, "number": procurement_number(request.number),
                         "title": request.title, "waiting_on": status["waiting_on"], "age_hours": status["age_hours"],
                         "nudges": len(status["nudges"])})
    rows.sort(key=lambda r: r["age_hours"], reverse=True)
    return {"sla_hours": sla, "count": len(rows), "rows": rows[:10]}


# --- Exception tasks ---------------------------------------------------------------------------------

def _invoice_requester(db: Session, invoice: Invoice) -> uuid.UUID | None:
    """The person who asked for what this invoice bills: the requester of the PO's request."""
    if invoice.po_id is None:
        return None
    return db.scalar(select(PurchaseRequest.requested_by).join(PurchaseOrder, PurchaseOrder.request_id == PurchaseRequest.id)
                     .where(PurchaseOrder.id == invoice.po_id))


def tasks_for_invoice(db: Session, invoice: Invoice) -> list[ExceptionTask]:
    return list(db.scalars(select(ExceptionTask).where(ExceptionTask.invoice_id == invoice.id)
                           .order_by(ExceptionTask.created_at)))


def ask(db: Session, user: User, invoice_id: uuid.UUID, assigned_to: uuid.UUID, question: str) -> ExceptionTask:
    if user.role not in ASKER_ROLES:
        raise Forbidden("Only finance or an admin can hold an invoice and ask a question.")
    invoice = load_invoice(db, user, invoice_id, lock=True)
    if invoice.status not in ASKABLE_STATUSES:
        raise Conflict("Only an invoice waiting for a decision can be held with a question.")
    question = question.strip()
    if not question:
        raise Invalid("Write the question.")
    assignee = db.scalar(select(User).where(User.id == assigned_to, User.org_id == user.org_id, User.active))
    if assignee is None:
        raise Invalid("Choose an active person in your organisation.")
    if assignee.id == user.id:
        raise Invalid("Ask someone else: you cannot answer your own question.")
    task = ExceptionTask(org_id=user.org_id, invoice_id=invoice.id, asked_by=user.id, assigned_to=assignee.id,
                         question=question)
    db.add(task)
    db.flush()
    record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=user.id,
                 action="question_asked", payload={"task_id": task.id, "assigned_to": assignee.id,
                                                   "assigned_to_name": assignee.full_name, "question": question})
    return task


def answer(db: Session, user: User, task_id: uuid.UUID, text: str) -> ExceptionTask:
    task = db.scalar(select(ExceptionTask).where(ExceptionTask.id == task_id, ExceptionTask.org_id == user.org_id)
                     .with_for_update())
    if task is None or task.assigned_to != user.id:
        # Another person's task is "not found", like another org's records.
        raise NotFound("Question not found.")
    if task.status != "open":
        raise Conflict("This question has already been answered.")
    text = text.strip()
    if not text:
        raise Invalid("Write an answer.")
    task.status, task.answer, task.answered_at = "answered", text, datetime.now(UTC)
    record_event(db, org_id=task.org_id, entity_type="invoice", entity_id=task.invoice_id, actor_id=user.id,
                 action="question_answered", payload={"task_id": task.id, "answer": text})
    return task


def close_tasks_on_decision(db: Session, invoice: Invoice, actor_id: uuid.UUID) -> None:
    """A decision ends the conversation: answered tasks close with it (called by review.decide)."""
    closed = []
    for task in tasks_for_invoice(db, invoice):
        if task.status != "closed":
            task.status, task.closed_at = "closed", datetime.now(UTC)
            closed.append(task.id)
    if closed:
        record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=actor_id,
                     action="questions_closed", payload={"task_ids": closed})


def task_view(db: Session, user: User, invoice: Invoice) -> dict[str, Any]:
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == invoice.org_id)).all())
    tasks = tasks_for_invoice(db, invoice)
    return {
        "tasks": [{"id": t.id, "asked_by": names.get(t.asked_by), "assigned_to": names.get(t.assigned_to),
                   "assigned_to_id": t.assigned_to, "question": t.question, "answer": t.answer, "status": t.status,
                   "asked_at": t.created_at, "answered_at": t.answered_at,
                   "can_answer": t.assigned_to == user.id and t.status == "open"} for t in tasks],
        "can_ask": user.role in ASKER_ROLES and invoice.status in ASKABLE_STATUSES,
        "suggested_assignee_id": _invoice_requester(db, invoice),
    }
