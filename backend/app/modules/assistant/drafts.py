"""AI drafts around the workflows (BUILD_PLAN v2.3 change 26, v2.4 change 33; PROMPTS Step 24).

Three helpers, each with the same shape: the server computes the facts, the AI only words them,
a person decides what to do, and a deterministic fallback keeps working without AI.

- Intake draft: one sentence → a pre-filled request form. The AI picks the category and splits
  lines with quantities; it never prices anything. Rates come from the last price actually paid on
  a PO for a similar item, otherwise they stay blank for the requester to fill. The approval chain
  and budget effect are computed by the same code that will enforce them.
- Exception note: a message to the vendor or requester about a held invoice, written from the rule
  results only, checked for ₹ figures; the template version is used if the AI is off or strays.
- "What changed" (DualEntry's flux analysis): this period against the previous one, computed by SQL;
  the AI rewrites the comparison as 3–5 bullets, ₹-checked, with template bullets as the fallback.
"""

import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ai_prompts import DRAFT_PROMPT_VERSION, FLUX_SYSTEM, INTAKE_SYSTEM, NOTE_SYSTEM
from app.models import Category, Invoice, PoLine, PurchaseOrder, PurchaseRequest, User, Vendor
from app.modules.assistant.service import unmatched_amounts
from app.modules.audit.service import to_jsonable
from app.modules.insights import service as insights
from app.modules.invoices.service import load_invoice
from app.modules.procurement import service as procurement
from app.modules.workflows import budgets
from app.modules.workflows.budgets import rupees
from app.ports.assistant import AssistantUnavailable
from app.ports.extractor import ExtractorUnavailable

ZERO = Decimal("0")
CENT = Decimal("0.01")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "new", "our", "per", "set", "pcs", "nos", "units", "unit", "need", "needed",
         "please", "buy", "get", "some", "team", "office", "inch", "year"}
STEP_WORDS = {"manager": "Requester's manager", "approver": "Approver", "finance": "Finance", "admin": "Admin"}
UNAVAILABLE = (AssistantUnavailable, ExtractorUnavailable)


# --- Intake draft ----------------------------------------------------------------------------------------

class DraftLine(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    qty: Decimal = Field(gt=0, le=Decimal("1000000"))


class DraftOut(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    justification: str = Field(default="", max_length=4000)
    category: str
    cost_center: str = Field(default="", max_length=60)
    needed_by: str = ""
    lines: list[DraftLine] = Field(min_length=1, max_length=20)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in _STOP}


def last_paid_rate(db: Session, org_id: uuid.UUID, category_id: uuid.UUID, description: str) -> dict[str, Any] | None:
    """The most recent PO price for a similar item: at least half of the draft's words must appear in the
    PO line's description or item code. POs raised from this category win over other POs."""
    wanted = _words(description)
    if not wanted:
        return None
    rows = db.execute(select(PoLine, PurchaseOrder, PurchaseRequest.category_id)
                      .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                      .outerjoin(PurchaseRequest, PurchaseRequest.id == PurchaseOrder.request_id)
                      .where(PoLine.org_id == org_id)).all()
    best = None
    for line, po, po_category in rows:
        have = _words(f"{line.description} {line.item_code.replace('-', ' ')}")
        overlap = len(wanted & have) / len(wanted)
        if overlap < 0.5:
            continue
        key = (po_category == category_id, overlap, po.po_date or date.min)
        if best is None or key > best[0]:
            best = (key, line, po)
    if best is None:
        return None
    _, line, po = best
    vendor = db.get(Vendor, po.vendor_id) if po.vendor_id else None
    return {"rate": line.rate, "source": f"last paid on {po.po_number or po.erp_ref}"
            f"{f' ({vendor.name})' if vendor else ''}{f', {po.po_date:%d %b %Y}' if po.po_date else ''}"}


def _chain_words(db: Session, steps: list[dict]) -> list[str]:
    out = []
    for step in steps:
        if step["label"]:
            named = db.get(User, step["approver_id"])
            out.append(f"{step['label']} ({named.full_name})" if named else step["label"])
        else:
            out.append(STEP_WORDS.get(step["role"], step["role"]))
    return out


def draft_request(db: Session, user: User, text: str, drafter: Any) -> dict[str, Any]:
    text = text.strip()[:1000]
    categories = list(db.scalars(select(Category).where(Category.org_id == user.org_id, Category.active)
                                 .order_by(Category.name)))
    if drafter is None or not categories:
        return {"available": False, "message": "The intake assistant is unavailable. Fill the form below."}
    names = [c.name for c in categories]
    schema = {"type": "object", "additionalProperties": False,
              "required": ["title", "justification", "category", "cost_center", "needed_by", "lines"],
              "properties": {
                  "title": {"type": "string"}, "justification": {"type": "string"},
                  "category": {"type": "string", "enum": names}, "cost_center": {"type": "string"},
                  "needed_by": {"type": "string", "description": "YYYY-MM-DD or empty"},
                  "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["description", "qty"],
                                                       "properties": {"description": {"type": "string"},
                                                                      "qty": {"type": "string"}}}}}}
    prompt = f"Today is {budgets.today_ist().isoformat()}. Categories: {', '.join(names)}.\nSentence: {text}"
    try:
        raw = drafter.json(INTAKE_SYSTEM, prompt, schema)
        draft = DraftOut.model_validate(raw)
    except UNAVAILABLE:
        return {"available": False, "message": "The intake assistant is unavailable. Fill the form below."}
    except ValidationError:
        return {"available": False, "message": "The intake assistant could not make sense of that. Fill the form below."}
    category = next((c for c in categories if c.name == draft.category), None)
    if category is None:
        return {"available": False, "message": "The intake assistant picked an unknown category. Fill the form below."}

    warnings = []
    needed_by = None
    try:
        needed = date.fromisoformat(draft.needed_by) if draft.needed_by else None
        if needed and budgets.today_ist() <= needed <= budgets.today_ist().replace(year=budgets.today_ist().year + 2):
            needed_by = needed
        elif needed:
            warnings.append("The date in your sentence was in the past or too far ahead, so it was left empty.")
    except ValueError:
        warnings.append("The date could not be read, so it was left empty.")

    lines, amount, priced = [], ZERO, 0
    for line in draft.lines:
        qty = line.qty.quantize(Decimal("0.001"))
        price = last_paid_rate(db, user.org_id, category.id, line.description)
        lines.append({"description": line.description, "qty": qty,
                      "est_rate": price["rate"] if price else None,
                      "rate_source": price["source"] if price else "no past price: please enter the rate"})
        if price:
            priced += 1
            amount += procurement.line_amount(qty, price["rate"])
    all_priced = priced == len(lines)
    if not all_priced:
        warnings.append("Some lines have no past price. Enter those rates; the amount and approvals below use the priced lines only.")
    chain = procurement.chain_preview(db, user.org_id, category.id, amount)
    cost_center = draft.cost_center.strip().upper()[:60]
    return {
        "available": True,
        "draft": {"category_id": category.id, "category": category.name, "title": draft.title.strip(),
                  "justification": draft.justification.strip(), "cost_center": cost_center, "needed_by": needed_by,
                  "lines": lines},
        "amount": amount, "all_priced": all_priced,
        "approval_chain": _chain_words(db, chain),
        "budget": budgets.check(db, user.org_id, cost_center, amount) if cost_center else None,
        "warnings": warnings,
        "ai_draft": {"model_id": drafter.model_id, "prompt_version": DRAFT_PROMPT_VERSION},
    }


# --- Exception note --------------------------------------------------------------------------------------

def _note_facts(db: Session, invoice: Invoice) -> dict[str, Any]:
    match = insights.latest_matches(db, [invoice.id]).get(invoice.id)
    problems = [] if match is None else [
        {"check": r.get("code"), "message": r.get("message"), "amount_at_risk": r.get("amount_at_risk")}
        for r in match.rule_results if r.get("status") == "fail"]
    return to_jsonable({"invoice_no": invoice.invoice_no, "vendor": invoice.vendor_name,
                        "total": rupees(invoice.total or ZERO), "amount_at_risk": rupees(match.amount_at_risk if match else ZERO),
                        "problems": problems})


def template_note(facts: dict[str, Any], audience: str) -> str:
    greeting = f"Dear {facts['vendor'] or 'supplier'}," if audience == "vendor" else "Hello,"
    lines = [greeting, "",
             f"Invoice {facts['invoice_no']} ({facts['total']}) could not be approved yet. "
             f"{facts['amount_at_risk']} is on hold because:"]
    lines += [f"- {p['message']}" for p in facts["problems"]] or ["- it needs a reviewer's check."]
    lines += ["", "Please send a corrected invoice or the supporting document." if audience == "vendor"
              else "Please confirm whether this was agreed, and share any supporting document.",
              "", "Thank you."]
    return "\n".join(lines)


def draft_note(db: Session, user: User, invoice_id: uuid.UUID, audience: str, drafter: Any) -> dict[str, Any]:
    invoice = load_invoice(db, user, invoice_id)
    facts = _note_facts(db, invoice)
    fallback = {"text": template_note(facts, audience), "source": "template (no AI)"}
    if drafter is None:
        return fallback
    try:
        text = drafter.text(NOTE_SYSTEM, f"Audience: {audience}.\nCheck results: {facts}")
    except UNAVAILABLE:
        return fallback
    # A note that names a rupee figure the checks did not produce is not sent to anyone: use the template.
    if unmatched_amounts(text, [facts]):
        return {**fallback, "note": "The AI version mentioned an amount not in the check results, so the template is shown."}
    return {"text": text, "source": drafter.model_id}


# --- "What changed" -------------------------------------------------------------------------------------

_FLUX_CACHE: dict[tuple, dict[str, Any]] = {}


def _previous_start(period: str, start: datetime) -> datetime:
    local = start.astimezone(insights.IST).date()
    months = 1 if period == "month" else 3
    month = local.month - months
    year = local.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return datetime(year, month, 1, tzinfo=insights.IST).astimezone(UTC)


def _numbers(db: Session, scope: insights.Scope, start: datetime, end: datetime) -> dict[str, Any]:
    by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
    categories = dict(db.execute(select(Category.id, Category.name).where(Category.org_id == scope.org_id)).all())
    query = insights.request_filter(select(PurchaseRequest), scope).where(
        PurchaseRequest.status.in_(insights.APPROVED_REQUEST_STATUSES),
        PurchaseRequest.created_at >= start, PurchaseRequest.created_at < end)
    for r in db.scalars(query):
        by_category[categories.get(r.category_id, "Other")] += r.amount
    out: dict[str, Any] = {"approved_spend": sum(by_category.values(), ZERO), "spend_by_category": dict(by_category)}
    if scope.role != "requester":
        invoices = list(db.scalars(select(Invoice).where(Invoice.org_id == scope.org_id, Invoice.created_at >= start,
                                                          Invoice.created_at < end)))
        latest = insights.latest_matches(db, [i.id for i in invoices])
        held = [i for i in invoices if i.status in insights.ON_HOLD_INVOICE_STATUSES]
        out.update({"invoices": len(invoices),
                    "approved_invoices_total": sum((i.total or ZERO for i in invoices if i.status == "approved"), ZERO),
                    "on_hold": len(held),
                    "at_risk": sum((latest[i.id].amount_at_risk for i in held if i.id in latest), ZERO)})
    return out


def flux(db: Session, scope: insights.Scope, period: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start = insights.period_start(period, now.astimezone(insights.IST).date())
    previous = _previous_start(period, start)
    current, before = _numbers(db, scope, start, now), _numbers(db, scope, previous, start)
    names = sorted(set(current["spend_by_category"]) | set(before["spend_by_category"]))
    changes = sorted(({"category": n, "now": current["spend_by_category"].get(n, ZERO),
                       "before": before["spend_by_category"].get(n, ZERO)} for n in names),
                     key=lambda c: abs(c["now"] - c["before"]), reverse=True)
    return {"period": period, "this_period": {k: v for k, v in current.items() if k != "spend_by_category"},
            "previous_period": {k: v for k, v in before.items() if k != "spend_by_category"},
            "category_changes": [{**c, "change": c["now"] - c["before"]} for c in changes[:5]]}


def template_bullets(data: dict[str, Any]) -> list[str]:
    now, before = data["this_period"], data["previous_period"]
    label = "this month" if data["period"] == "month" else "this quarter"
    bullets = [f"Approved spend {label}: {rupees(now['approved_spend'])}, against {rupees(before['approved_spend'])} "
               "in the previous period."]
    for c in data["category_changes"][:2]:
        if c["change"]:
            direction = "up" if c["change"] > 0 else "down"
            bullets.append(f"{c['category']} is {direction} {rupees(abs(c['change']))} "
                           f"({rupees(c['before'])} → {rupees(c['now'])}).")
    if "on_hold" in now:
        bullets.append(f"Invoices on hold: {now['on_hold']} with {rupees(now['at_risk'])} at risk, against "
                       f"{before['on_hold']} with {rupees(before['at_risk'])} before.")
        bullets.append(f"Approved invoices: {rupees(now['approved_invoices_total'])}, against "
                       f"{rupees(before['approved_invoices_total'])} before.")
    return bullets[:5]


def flux_notes(db: Session, user: User, period: str, drafter: Any) -> dict[str, Any]:
    scope = insights.Scope(org_id=user.org_id, user_id=user.id, role=user.role)
    data = to_jsonable(flux(db, scope, period))
    # Same numbers + same writer → same bullets for a while; templates are cheap and never cached.
    key = (user.org_id, user.role, user.id if user.role == "requester" else None, period, str(data),
           getattr(drafter, "model_id", None))
    if key in _FLUX_CACHE:
        return _FLUX_CACHE[key]
    readable = {**data, "amounts_in_rupees": [rupees(Decimal(v)) for v in _amount_strings(data)]}
    result: dict[str, Any] = {"bullets": template_bullets(flux(db, scope, period)), "source": "template (no AI)",
                              "numbers": data}
    if drafter is not None:
        try:
            text = drafter.text(FLUX_SYSTEM, str(readable))
            bullets = [line.strip()[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]
            if bullets and not unmatched_amounts(" ".join(bullets), [data]):
                result = {"bullets": bullets[:5], "source": drafter.model_id, "numbers": data}
        except UNAVAILABLE:
            pass
    if result["source"] != "template (no AI)":
        if len(_FLUX_CACHE) > 500:  # a demo-sized cache; it only saves repeat AI calls
            _FLUX_CACHE.clear()
        _FLUX_CACHE[key] = result
    return result


def _amount_strings(value: Any) -> list[str]:
    out = []
    if isinstance(value, dict):
        for v in value.values():
            out += _amount_strings(v)
    elif isinstance(value, list):
        for v in value:
            out += _amount_strings(v)
    elif isinstance(value, str) and re.fullmatch(r"-?\d+\.\d{2}", value):
        out.append(value)
    return out
