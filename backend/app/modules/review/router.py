"""HTTP routes for invoice decisions and the audit trail (BUILD_PLAN §2 audit, §9; PROMPTS Step 9).

The audit routes list entities (invoices and purchase requests), show one entity's timeline,
and verify its hash chain: anyone can press "Verify chain" and see whether history was altered.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.models import (
    AuditEvent,
    Document,
    GoodsReceipt,
    GrnLine,
    Invoice,
    PoLine,
    PurchaseOrder,
    PurchaseRequest,
    RequestApproval,
    User,
)
from app.modules.audit.service import timeline, verify_chain
from app.modules.invoices.router import DETAIL_EXTENSIONS, build_detail
from app.modules.invoices.schemas import InvoiceDetail
from app.modules.review import service

router = APIRouter(tags=["review and audit"])
AUDIT_ROLES = ("approver", "finance", "admin")


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_correction"]
    reason: str | None = Field(default=None, max_length=2000)


def _add_review(db: Session, user: User, invoice: Invoice, detail: InvoiceDetail) -> None:
    detail.decisions = service.decisions_of(db, invoice)
    refusal_any = service.decision_refusal(db, user, invoice, "reject")
    detail.allowed.decide = refusal_any is None
    if refusal_any is None:
        approve = service.decision_refusal(db, user, invoice, "approve")
        detail.allowed.approve_blocked_reason = approve.message if approve else None


DETAIL_EXTENSIONS.append(_add_review)


@router.post("/invoices/{invoice_id}/decision", response_model=InvoiceDetail)
def decide(invoice_id: uuid.UUID, body: DecisionIn, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    invoice = service.decide(db, user, invoice_id, body.decision, body.reason)
    db.commit()
    return build_detail(db, user, invoice)


@router.post("/invoices/{invoice_id}/rematch", response_model=InvoiceDetail)
def rematch(invoice_id: uuid.UUID, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    invoice = service.rematch(db, user, invoice_id)
    db.commit()
    return build_detail(db, user, invoice)


class AuditEntity(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    label: str
    status: str
    events: int
    last_action: str


class AuditTimeline(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    label: str
    chain_valid: bool
    events: list[dict]


def _label(db: Session, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> tuple[str, str] | None:
    if entity_type == "invoice":
        row = db.execute(select(Invoice, Document.filename).join(Document, Document.id == Invoice.document_id)
                         .where(Invoice.id == entity_id, Invoice.org_id == org_id)).first()
        if row:
            invoice, filename = row
            return f"{invoice.invoice_no or filename} · {invoice.vendor_name or 'vendor not read yet'}", invoice.status
    elif entity_type == "purchase_request":
        request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == entity_id,
                                                          PurchaseRequest.org_id == org_id))
        if request:
            return f"PR-{request.number:04d} · {request.title}", request.status
    return None


@router.get("/audit/entities", response_model=list[AuditEntity],
            dependencies=[Depends(require_roles(*AUDIT_ROLES))])
def audit_entities(user: CurrentUser, db: DbSession) -> list[AuditEntity]:
    rows = db.execute(
        select(AuditEvent.entity_type, AuditEvent.entity_id, func.count(), func.max(AuditEvent.seq))
        .where(AuditEvent.org_id == user.org_id, AuditEvent.entity_type.in_(("invoice", "purchase_request")))
        .group_by(AuditEvent.entity_type, AuditEvent.entity_id)).all()
    out = []
    for entity_type, entity_id, count, last_seq in rows:
        labelled = _label(db, user.org_id, entity_type, entity_id)
        if not labelled:
            continue
        last_action = db.scalar(select(AuditEvent.action).where(AuditEvent.entity_id == entity_id,
                                                                AuditEvent.seq == last_seq))
        out.append(AuditEntity(entity_type=entity_type, entity_id=entity_id, label=labelled[0], status=labelled[1],
                               events=count, last_action=last_action))
    return sorted(out, key=lambda e: (e.entity_type, e.label))


@router.get("/audit/{entity_id}", response_model=AuditTimeline, dependencies=[Depends(require_roles(*AUDIT_ROLES))])
def audit_timeline(entity_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AuditTimeline:
    entity_type = db.scalar(select(AuditEvent.entity_type).where(AuditEvent.entity_id == entity_id,
                                                                 AuditEvent.org_id == user.org_id).limit(1))
    labelled = _label(db, user.org_id, entity_type, entity_id) if entity_type else None
    if not labelled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No audit trail found.")
    events = timeline(db, user.org_id, entity_id)
    return AuditTimeline(entity_type=entity_type, entity_id=entity_id, label=labelled[0],
                         chain_valid=verify_chain(db, entity_id),
                         events=[{**e, "at": e["at"].isoformat()} for e in events])


# --- Control Graph (BUILD_PLAN §1 step 13, §11 M5; PROMPTS Step 10) ------------------------------
# One chain per invoice or per request: request → approvals → PO → receipts → invoice → match →
# decision → ERP draft. Read-only; every node links to the page that holds its detail.

def _node(kind: str, label: str, state: str, detail: str = "", href: str | None = None) -> dict:
    """state: done | current | blocked | pending (not reached yet) | skipped (does not apply)."""
    return {"kind": kind, "label": label, "state": state, "detail": detail, "href": href}


def _request_nodes(db: Session, request: PurchaseRequest | None, po_origin: str | None) -> list[dict]:
    if request is None:
        note = "This PO was created directly in the ERP, not through an Orrfin request."
        return [_node("request", "Purchase request", "skipped", note if po_origin else "No request linked.")]
    state = {"approved": "done", "po_drafted": "done", "po_open": "done", "rejected": "blocked",
             "returned": "blocked", "cancelled": "blocked"}.get(request.status, "current")
    nodes = [_node("request", f"PR-{request.number:04d} · {request.title}", state,
                   f"₹{request.amount:,.2f} · {request.status.replace('_', ' ')}", f"/requests/{request.id}")]
    steps = db.execute(select(RequestApproval, User.full_name).outerjoin(User, User.id == RequestApproval.approver_id)
                       .where(RequestApproval.request_id == request.id,
                              RequestApproval.round == request.approval_round)
                       .order_by(RequestApproval.step)).all()
    for step, name in steps:
        step_state = {"approve": "done", "reject": "blocked", "return": "blocked"}.get(step.decision or "", "pending")
        detail = f"{step.decision} · {name}" if step.decision else "waiting"
        nodes.append(_node("approval", f"Approval step {step.step}: {step.required_role}", step_state, detail,
                           f"/requests/{request.id}"))
    return nodes


def _po_nodes(db: Session, po: PurchaseOrder | None) -> list[dict]:
    if po is None:
        return [_node("po", "Purchase order", "pending", "Orrfin drafts the PO in ERPNext in Step 13."),
                _node("receipt", "Goods receipt", "pending")]
    nodes = [_node("po", po.erp_ref, "done" if po.status in ("open", "to_bill", "completed") else "blocked",
                   f"{po.status.replace('_', ' ')} · ₹{po.grand_total:,.2f}", f"/pos/{po.id}")]
    receipts = db.scalars(select(GoodsReceipt).distinct().join(GrnLine, GrnLine.receipt_id == GoodsReceipt.id)
                          .join(PoLine, PoLine.id == GrnLine.po_line_id).where(PoLine.po_id == po.id)
                          .order_by(GoodsReceipt.erp_ref)).all()
    if not receipts:
        nodes.append(_node("receipt", "Goods receipt", "pending", "Nothing received yet.", f"/pos/{po.id}"))
    for receipt in receipts:
        nodes.append(_node("receipt", receipt.erp_ref, "done", f"received {receipt.posting_date}", f"/pos/{po.id}"))
    return nodes


def _invoice_nodes(db: Session, invoice: Invoice) -> list[dict]:
    from app.modules.invoices.match_job import match_view

    reading = {"extracting": "current", "needs_review": "current", "manual_entry": "current",
               "correction_requested": "current"}.get(invoice.status, "done")
    amount = f" · ₹{invoice.total:,.2f}" if invoice.total is not None else ""
    nodes = [_node("invoice", f"Invoice {invoice.invoice_no or '(being read)'}", reading,
                   f"{invoice.vendor_name or invoice.status}{amount}", f"/invoices/{invoice.id}")]
    view = match_view(db, invoice)
    if view is None:
        nodes.append(_node("match", "Match", "pending", "Runs after finance confirms the fields."))
    else:
        failed = sorted({r["code"] for r in view["rule_results"] if r["status"] == "fail"})
        nodes.append(_node("match", f"Match: {view['outcome']}",
                           {"matched": "done", "exception": "blocked", "stale": "blocked"}[view["outcome"]],
                           ", ".join(failed) or "all rules passed", f"/invoices/{invoice.id}"))
    decided = service.decisions_of(db, invoice)
    if decided:
        last = decided[-1]
        reason = f": “{last['reason']}”" if last["reason"] else ""
        nodes.append(_node("decision", f"Decision: {last['decision'].replace('_', ' ')}",
                           "done" if last["decision"] == "approve" else "blocked",
                           f"by {last['reviewer_name']}{reason}", f"/invoices/{invoice.id}"))
    else:
        nodes.append(_node("decision", "Decision", "pending", "A named reviewer approves or rejects."))
    nodes.append(_node("erp_draft", "Draft bill in ERPNext", "pending",
                       "Ready to draft (Step 13)" if invoice.status == "approved" else "After approval"))
    return nodes


@router.get("/control-graph", dependencies=[Depends(require_roles("buyer", *AUDIT_ROLES))])
def control_graph(user: CurrentUser, db: DbSession, invoice_id: uuid.UUID | None = None,
                  request_id: uuid.UUID | None = None) -> dict:
    if invoice_id:
        invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == user.org_id))
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
        po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
        request = db.get(PurchaseRequest, po.request_id) if po and po.request_id else None
        nodes = _request_nodes(db, request, po.origin if po else None) + _po_nodes(db, po) + _invoice_nodes(db, invoice)
        return {"subject": "invoice", "id": str(invoice.id), "nodes": nodes}
    if request_id:
        request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.id == request_id,
                                                          PurchaseRequest.org_id == user.org_id))
        if request is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.request_id == request.id))
        nodes = _request_nodes(db, request, None) + _po_nodes(db, po)
        invoices = db.scalars(select(Invoice).where(Invoice.po_id == po.id)).all() if po else []
        for invoice in invoices:
            nodes += _invoice_nodes(db, invoice)
        if not invoices:
            nodes += [_node("invoice", "Supplier invoice", "pending"), _node("match", "Match", "pending"),
                      _node("decision", "Decision", "pending"), _node("erp_draft", "Draft bill in ERPNext", "pending")]
        return {"subject": "request", "id": str(request.id), "nodes": nodes}
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give invoice_id or request_id.")
