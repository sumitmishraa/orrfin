"""RFQs, sealed supplier quotes, comparison and a human award (BUILD_PLAN change 43, §6f, §9).

draft → open (weights frozen, invited suppliers can quote) → closed (quotes revealed) → awarded.
Rules held here, on the server:
- quotes are sealed: nobody at the buyer sees a quote, or how many there are, before the RFQ closes;
- the scoring weights are fixed when the RFQ opens, so they cannot be tuned to favour a quote;
- a person awards; awarding anything other than the top score needs a written reason;
- the award does not order anything: it creates a normal draft purchase request that goes
  through the same approvals as any other (§9), and only then becomes a draft PO (§8);
- a supplier on a risk hold, or not yet approved, cannot be invited or awarded.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import (
    Category, Quote, QuoteLine, RfqAward, RfqEvent, RfqInvite, RfqLine, RiskAssessment, Supplier, User,
)
from app.modules.audit.service import record_event, to_jsonable
from app.modules.entities.fx import CURRENCIES
from app.modules.entities.service import rate_on
from app.modules.notifications.service import notify
from app.modules.procurement import service as procurement
from app.modules.sourcing.compare import DEFAULT_WEIGHTS, QuoteIn, QuoteLineIn, compare, weight_problems

BUYER_ROLES = ("buyer", "finance", "admin")
VIEW_ROLES = ("buyer", "approver", "finance", "admin")
INVITABLE = ("approved", "handed_over", "active")


def _now() -> datetime:
    return datetime.now(UTC)


def audit(db: Session, rfq: RfqEvent, actor_id: uuid.UUID | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=rfq.org_id, entity_type="rfq", entity_id=rfq.id, actor_id=actor_id, action=action,
                 payload={"status": rfq.status, **(payload or {})})


def effective_status(rfq: RfqEvent) -> str:
    """An open RFQ past its closing time is closed, whether or not anyone pressed a button."""
    return "closed" if rfq.status == "open" and rfq.closes_at <= _now() else rfq.status


def label(rfq: RfqEvent) -> str:
    return f"RFQ-{rfq.number:04d}"


def _require(user: User, roles: tuple[str, ...], what: str) -> None:
    if user.role not in roles:
        raise Forbidden(f"Your role cannot {what}.")


def load_rfq(db: Session, user: User, rfq_id: uuid.UUID, *, lock: bool = False) -> RfqEvent:
    _require(user, VIEW_ROLES, "see RFQs")
    query = select(RfqEvent).where(RfqEvent.id == rfq_id, RfqEvent.org_id == user.org_id)
    rfq = db.scalar(query.with_for_update() if lock else query)
    if rfq is None:
        raise NotFound("RFQ not found.")
    return rfq


def lines_of(db: Session, rfq: RfqEvent) -> list[RfqLine]:
    return list(db.scalars(select(RfqLine).where(RfqLine.rfq_id == rfq.id).order_by(RfqLine.line_no)))


def create_rfq(db: Session, user: User, *, title: str, category_id: uuid.UUID, currency: str, closes_at: datetime,
               lines: list[dict[str, Any]], weights: dict[str, int] | None) -> RfqEvent:
    _require(user, BUYER_ROLES, "create an RFQ")
    if db.scalar(select(Category.id).where(Category.id == category_id, Category.org_id == user.org_id)) is None:
        raise Invalid("Choose a category from the list.")
    if currency not in CURRENCIES:
        raise Invalid(f"The currency must be one of {', '.join(CURRENCIES)}.")
    weights = weights or dict(DEFAULT_WEIGHTS)
    problems = weight_problems(weights)
    if problems:
        raise Invalid(" ".join(problems))
    if not lines or len(lines) > 50:
        raise Invalid("An RFQ needs 1 to 50 lines.")
    number = (db.scalar(select(func.max(RfqEvent.number)).where(RfqEvent.org_id == user.org_id)) or 0) + 1
    rfq = RfqEvent(id=uuid.uuid4(), org_id=user.org_id, number=number, title=title.strip()[:200],
                   category_id=category_id, currency=currency, closes_at=closes_at, scoring=weights,
                   created_by=user.id, status="draft")
    db.add(rfq)
    db.flush()
    for n, line in enumerate(lines, start=1):
        qty = Decimal(str(line["qty"]))
        if qty <= 0 or not str(line.get("description", "")).strip():
            raise Invalid(f"Line {n}: describe the item and give a quantity above 0.")
        db.add(RfqLine(org_id=user.org_id, rfq_id=rfq.id, line_no=n, description=line["description"].strip()[:300],
                       qty=qty, uom=(line.get("uom") or "Nos")[:40]))
    audit(db, rfq, user.id, "created", {"weights": weights, "currency": currency})
    return rfq


def invite(db: Session, user: User, rfq_id: uuid.UUID, supplier_ids: list[uuid.UUID]) -> RfqEvent:
    _require(user, BUYER_ROLES, "invite suppliers")
    rfq = load_rfq(db, user, rfq_id, lock=True)
    if effective_status(rfq) not in ("draft", "open"):
        raise Conflict("Suppliers can only be invited before the RFQ closes.")
    suppliers = list(db.scalars(select(Supplier).where(Supplier.org_id == user.org_id, Supplier.id.in_(supplier_ids))))
    if len(suppliers) != len(set(supplier_ids)):
        raise NotFound("One of those suppliers was not found.")
    for supplier in suppliers:
        if supplier.status not in INVITABLE or supplier.on_hold:
            raise Conflict(f"{supplier.legal_name} is not an approved supplier without a risk hold.")
        if db.scalar(select(RfqInvite.id).where(RfqInvite.rfq_id == rfq.id, RfqInvite.supplier_id == supplier.id)) is None:
            db.add(RfqInvite(org_id=user.org_id, rfq_id=rfq.id, supplier_id=supplier.id))
    db.flush()
    audit(db, rfq, user.id, "suppliers_invited", {"suppliers": sorted(str(s.id) for s in suppliers)})
    return rfq


def open_rfq(db: Session, user: User, rfq_id: uuid.UUID) -> RfqEvent:
    _require(user, BUYER_ROLES, "open an RFQ")
    rfq = load_rfq(db, user, rfq_id, lock=True)
    if rfq.status != "draft":
        raise Conflict("Only a draft RFQ can be opened.")
    if rfq.closes_at <= _now():
        raise Invalid("Set a closing time in the future before opening the RFQ.")
    if db.scalar(select(func.count()).select_from(RfqInvite).where(RfqInvite.rfq_id == rfq.id)) == 0:
        raise Invalid("Invite at least one supplier first.")
    rfq.status = "open"
    audit(db, rfq, user.id, "opened", {"weights": rfq.scoring, "closes_at": rfq.closes_at.isoformat()})
    return rfq


def close_rfq(db: Session, user: User, rfq_id: uuid.UUID) -> RfqEvent:
    _require(user, BUYER_ROLES, "close an RFQ")
    rfq = load_rfq(db, user, rfq_id, lock=True)
    if effective_status(rfq) not in ("open", "closed") or rfq.status != "open":
        raise Conflict("Only an open RFQ can be closed.")
    rfq.status = "closed"
    audit(db, rfq, user.id, "closed", {})
    return rfq


# --- Comparison and award -------------------------------------------------------------------------

def _quote_inputs(db: Session, rfq: RfqEvent) -> list[QuoteIn]:
    by_line = {line.id: line for line in lines_of(db, rfq)}
    inputs = []
    for quote, supplier in db.execute(select(Quote, Supplier).join(Supplier, Supplier.id == Quote.supplier_id)
                                      .where(Quote.rfq_id == rfq.id)).all():
        risk = db.scalar(select(RiskAssessment.score).where(RiskAssessment.supplier_id == supplier.id)
                         .order_by(RiskAssessment.created_at.desc()).limit(1))
        fx = None
        if quote.currency != rfq.currency:
            row = rate_on(db, rfq.org_id, quote.currency, rfq.currency, rfq.closes_at.date())
            fx = row.rate if row else None
        quote_lines = db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id))
        inputs.append(QuoteIn(id=str(quote.id), supplier_name=supplier.legal_name, currency=quote.currency,
                              lines=[QuoteLineIn(by_line[ql.rfq_line_id].qty, ql.rate, ql.tax_rate) for ql in quote_lines],
                              freight=quote.freight, payment_terms_days=quote.payment_terms_days,
                              delivery_days=quote.delivery_days, risk_score=risk, fx_rate=fx))
    return inputs


def comparison(db: Session, user: User, rfq_id: uuid.UUID) -> list[dict[str, Any]]:
    rfq = load_rfq(db, user, rfq_id)
    if effective_status(rfq) in ("draft", "open"):
        # Sealed bids: before closing, not even the number of quotes is shown.
        raise Conflict("Quotes stay sealed until the RFQ closes.")
    return [to_jsonable(row.__dict__) for row in compare(_quote_inputs(db, rfq), rfq.currency, rfq.scoring)]


def award(db: Session, user: User, rfq_id: uuid.UUID, quote_id: uuid.UUID, reason: str | None):
    """Award one quote and raise the normal draft purchase request for it. Returns (rfq, request)."""
    _require(user, BUYER_ROLES, "award an RFQ")
    rfq = load_rfq(db, user, rfq_id, lock=True)
    if effective_status(rfq) != "closed":
        raise Conflict("An RFQ can be awarded once, after it closes.")
    rows = comparison(db, user, rfq_id)
    chosen = next((r for r in rows if r["quote_id"] == str(quote_id)), None)
    if chosen is None:
        raise NotFound("Quote not found on this RFQ.")
    if chosen["score"] is None:
        raise Conflict("This quote could not be scored (no exchange rate), so it cannot be awarded.")
    reason = (reason or "").strip() or None
    if chosen["quote_id"] != rows[0]["quote_id"] and not reason:
        raise Invalid("This is not the top-scoring quote. Write why you award it.")
    quote = db.get(Quote, quote_id)
    supplier = db.get(Supplier, quote.supplier_id)
    if supplier.on_hold or supplier.status not in INVITABLE:
        raise Conflict(f"{supplier.legal_name} is on a risk hold or no longer approved.")
    if quote.valid_until < date.today():
        raise Conflict("This quote has expired.")
    rfq_lines = {line.id: line for line in lines_of(db, rfq)}
    fx = Decimal(1) if quote.currency == rfq.currency else rate_on(db, rfq.org_id, quote.currency, rfq.currency,
                                                                  rfq.closes_at.date()).rate
    lines = [procurement.LineInput(description=rfq_lines[ql.rfq_line_id].description, qty=rfq_lines[ql.rfq_line_id].qty,
                                   est_rate=(ql.rate * fx).quantize(Decimal("0.01")))
             for ql in db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id))]
    request = procurement.create_request(
        db, user, category_id=rfq.category_id, title=f"{label(rfq)}: {rfq.title}"[:200],
        justification=f"Awarded to {supplier.legal_name} from {label(rfq)}." + (f" Reason: {reason}" if reason else ""),
        cost_center="", needed_by=None, lines=lines, suggested_vendor_id=supplier.vendor_id)
    request.currency = rfq.currency
    db.add(RfqAward(org_id=rfq.org_id, rfq_id=rfq.id, quote_id=quote.id, awarded_by=user.id, reason=reason,
                    comparison_snapshot={"rows": rows, "weights": rfq.scoring}))
    rfq.status, rfq.request_id = "awarded", request.id
    audit(db, rfq, user.id, "awarded", {"quote_id": quote.id, "supplier": supplier.legal_name, "reason": reason,
                                        "score": chosen["score"], "top_score": rows[0]["score"], "request_id": request.id})
    return rfq, request


def detail(db: Session, user: User, rfq: RfqEvent) -> dict[str, Any]:
    status = effective_status(rfq)
    invited = db.execute(select(Supplier.id, Supplier.legal_name).join(RfqInvite, RfqInvite.supplier_id == Supplier.id)
                         .where(RfqInvite.rfq_id == rfq.id)).all()
    return {"id": rfq.id, "number": label(rfq), "title": rfq.title, "currency": rfq.currency, "status": status,
            "closes_at": rfq.closes_at, "weights": rfq.scoring, "category_id": rfq.category_id,
            "request_id": rfq.request_id,
            "lines": [{"id": l.id, "line_no": l.line_no, "description": l.description, "qty": l.qty, "uom": l.uom}
                      for l in lines_of(db, rfq)],
            "invited": [{"id": i, "legal_name": n} for i, n in invited],
            "comparison": comparison(db, user, rfq.id) if status in ("closed", "awarded") else None}


def list_rfqs(db: Session, user: User) -> list[dict[str, Any]]:
    _require(user, VIEW_ROLES, "see RFQs")
    rows = db.scalars(select(RfqEvent).where(RfqEvent.org_id == user.org_id).order_by(RfqEvent.number.desc()))
    return [{"id": r.id, "number": label(r), "title": r.title, "status": effective_status(r), "closes_at": r.closes_at,
             "currency": r.currency} for r in rows]


# --- Supplier portal side ----------------------------------------------------------------------------

def portal_rfqs(db: Session, supplier: Supplier) -> list[dict[str, Any]]:
    """RFQs this supplier was invited to and that have opened, with its own quote only."""
    rows = db.scalars(select(RfqEvent).join(RfqInvite, RfqInvite.rfq_id == RfqEvent.id)
                      .where(RfqInvite.supplier_id == supplier.id, RfqEvent.org_id == supplier.org_id,
                             RfqEvent.status != "draft").order_by(RfqEvent.closes_at))
    out = []
    for rfq in rows:
        mine = db.scalar(select(Quote).where(Quote.rfq_id == rfq.id, Quote.supplier_id == supplier.id))
        rates = {ql.rfq_line_id: ql for ql in db.scalars(select(QuoteLine).where(QuoteLine.quote_id == mine.id))} if mine else {}
        out.append({"id": rfq.id, "number": label(rfq), "title": rfq.title, "currency": rfq.currency,
                    "closes_at": rfq.closes_at, "status": effective_status(rfq), "weights": rfq.scoring,
                    "lines": [{"id": l.id, "description": l.description, "qty": l.qty, "uom": l.uom,
                               "rate": rates[l.id].rate if l.id in rates else None,
                               "tax_rate": rates[l.id].tax_rate if l.id in rates else None} for l in lines_of(db, rfq)],
                    "my_quote": {"currency": mine.currency, "freight": mine.freight,
                                 "payment_terms_days": mine.payment_terms_days, "delivery_days": mine.delivery_days,
                                 "valid_until": mine.valid_until} if mine else None})
    return out


def submit_quote(db: Session, supplier: Supplier, contact_id: uuid.UUID, rfq_id: uuid.UUID, *, currency: str,
                 freight: Decimal, payment_terms_days: int, delivery_days: int, valid_until: date,
                 lines: dict[uuid.UUID, tuple[Decimal, Decimal]]) -> Quote:
    """Create or replace this supplier's quote while the RFQ is open. `lines`: rfq line id → (rate, tax %)."""
    rfq = db.scalar(select(RfqEvent).join(RfqInvite, RfqInvite.rfq_id == RfqEvent.id)
                    .where(RfqEvent.id == rfq_id, RfqInvite.supplier_id == supplier.id).with_for_update(of=RfqEvent))
    if rfq is None:
        raise NotFound("RFQ not found.")  # not invited reads the same as not existing
    if effective_status(rfq) != "open":
        raise Conflict("This RFQ is not open for quotes.")
    if supplier.on_hold:
        raise Conflict("Your account is on hold. Contact your customer.")
    if currency not in CURRENCIES:
        raise Invalid(f"Quote in one of {', '.join(CURRENCIES)}.")
    if freight < 0 or not 0 <= payment_terms_days <= 365 or not 0 <= delivery_days <= 365:
        raise Invalid("Freight cannot be negative; terms and delivery must be 0 to 365 days.")
    if valid_until < date.today():
        raise Invalid("The quote must be valid until today or later.")
    rfq_line_ids = {line.id for line in lines_of(db, rfq)}
    if set(lines) != rfq_line_ids:
        raise Invalid("Give a rate for every line, and only for the lines on this RFQ.")
    if any(rate < 0 or not 0 <= tax <= 100 for rate, tax in lines.values()):
        raise Invalid("Rates cannot be negative; tax is a percentage from 0 to 100.")
    quote = db.scalar(select(Quote).where(Quote.rfq_id == rfq.id, Quote.supplier_id == supplier.id))
    if quote is None:
        quote = Quote(id=uuid.uuid4(), org_id=rfq.org_id, rfq_id=rfq.id, supplier_id=supplier.id, currency=currency,
                      freight=freight, payment_terms_days=payment_terms_days, delivery_days=delivery_days,
                      valid_until=valid_until, submitted_by=contact_id)
        db.add(quote)
    else:
        quote.currency, quote.freight, quote.valid_until = currency, freight, valid_until
        quote.payment_terms_days, quote.delivery_days, quote.submitted_by = payment_terms_days, delivery_days, contact_id
        for old in db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id)):
            db.delete(old)
    db.flush()
    for line_id, (rate, tax) in lines.items():
        db.add(QuoteLine(org_id=rfq.org_id, quote_id=quote.id, rfq_line_id=line_id, rate=rate, tax_rate=tax))
    # The audit records that a quote arrived, not its prices: the buyer must not learn them before closing.
    audit(db, rfq, None, "quote_received", {"supplier_id": supplier.id})
    notify(db, org_id=rfq.org_id, user_id=rfq.created_by, kind="rfq_quote", title=f"A quote arrived on {label(rfq)}",
           link=f"/sourcing/{rfq.id}")
    return quote
