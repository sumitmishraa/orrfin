"""Invoice decisions: approve / reject / request correction (BUILD_PLAN §9; §11 M5; PROMPTS Step 9).

Rules, all enforced here on the server:
- only finance or an admin decides, and only on a matched invoice or an exception (409 otherwise);
- a match made stale by an ERP change must be re-run first (§6 rule 11, 409);
- whoever uploaded or edited the invoice cannot approve it (403);
- approving needs an approval limit at least the invoice total (403);
- rejecting, requesting a correction or approving an exception needs a reason (422).
An approved invoice is "ready for ERP draft"; the outbox write-back arrives in Steps 11-13.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, DomainError, Forbidden, Invalid
from app.models import Document, FieldEdit, Invoice, ReviewDecision, User
from app.modules.audit.service import record_event
from app.modules.invoices.match_job import current_staleness, start_match
from app.modules.invoices.service import load_invoice

DECIDER_ROLES = ("finance", "admin")
DECIDABLE_STATUSES = ("matched", "exception")
DECISIONS = {"approve": "approved", "reject": "rejected", "request_correction": "correction_requested"}


def decision_refusal(db: Session, user: User, invoice: Invoice, decision: str) -> DomainError | None:
    """Why `user` may not take `decision` on this invoice now, or None. Also drives the page's buttons."""
    if user.role not in DECIDER_ROLES:
        return Forbidden("Only finance or an admin can decide on invoices.")
    if invoice.status not in DECIDABLE_STATUSES:
        return Conflict("This invoice is not waiting for a decision.")
    if current_staleness(db, invoice):
        return Conflict("The PO or a goods receipt changed in the ERP after matching. Re-run the match first.")
    if decision != "approve":
        return None
    uploader = db.scalar(select(Document.uploaded_by).where(Document.id == invoice.document_id))
    if uploader == user.id:
        return Forbidden("You uploaded this invoice, so someone else must approve it.")
    if db.scalar(select(FieldEdit.id).where(FieldEdit.invoice_id == invoice.id, FieldEdit.edited_by == user.id).limit(1)):
        return Forbidden("You edited this invoice's fields, so someone else must approve it.")
    if invoice.total is not None and invoice.total > user.approval_limit:
        return Forbidden(f"₹{invoice.total:,.2f} is above your approval limit of ₹{user.approval_limit:,.2f}.")
    return None


def decide(db: Session, user: User, invoice_id: uuid.UUID, decision: str, reason: str | None) -> Invoice:
    if decision not in DECISIONS:
        raise Invalid("Decision must be approve, reject or request_correction.")
    invoice = load_invoice(db, user, invoice_id, lock=True)
    reason = (reason or "").strip() or None
    needs_reason = decision != "approve" or invoice.status == "exception"
    if needs_reason and not reason:
        raise Invalid("Give a reason: it is required to reject, to request a correction or to approve an exception.")
    refusal = decision_refusal(db, user, invoice, decision)
    if refusal:
        raise refusal
    previous = invoice.status
    invoice.status = DECISIONS[decision]
    db.add(ReviewDecision(org_id=invoice.org_id, invoice_id=invoice.id, reviewer_id=user.id, decision=decision,
                          reason=reason))
    record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=user.id,
                 action=f"decision_{decision}",
                 payload={"status": invoice.status, "from": previous, "reason": reason, "total": invoice.total})
    return invoice


def rematch(db: Session, user: User, invoice_id: uuid.UUID) -> Invoice:
    """Re-run the rules, e.g. after the ERP changed (stale) or after a sync brought new receipts."""
    if user.role not in DECIDER_ROLES:
        raise Forbidden("Only finance or an admin can re-run a match.")
    invoice = load_invoice(db, user, invoice_id, lock=True)
    if invoice.status not in DECIDABLE_STATUSES:
        raise Conflict("Only a matched invoice or an exception can be re-matched.")
    record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=user.id,
                 action="rematch_requested", payload={"status": "matching", "from": invoice.status})
    start_match(db, invoice, user.id)
    return invoice


def decisions_of(db: Session, invoice: Invoice) -> list[dict]:
    rows = db.execute(select(ReviewDecision, User.full_name).join(User, User.id == ReviewDecision.reviewer_id)
                      .where(ReviewDecision.invoice_id == invoice.id).order_by(ReviewDecision.created_at)).all()
    return [{"decision": d.decision, "reason": d.reason, "reviewer_name": name, "at": d.created_at.isoformat()}
            for d, name in rows]
