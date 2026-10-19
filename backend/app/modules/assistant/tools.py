"""The Orrfin Assistant's read-only tools (BUILD_PLAN v2.3 change 25, §4 assistant rule; ADR 0007).

Every tool is bound to the logged-in user and reuses the loader the pages use
(procurement.load_request, invoices.load_invoice, the insights/rules/budgets services), so the
assistant sees exactly what that user could open, and nothing more. No tool writes, calls an
ERP, or returns an invoice's printed text; invoice lines carry codes and numbers only.

Each record in a result carries a `ref` ({type, id, label}); the service links only to refs
that a tool actually returned in this turn.
"""

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.models import (
    Category,
    ExceptionTask,
    GrnLine,
    Invoice,
    InvoiceLine,
    PoLine,
    PurchaseOrder,
    PurchaseRequest,
    User,
    Vendor,
)
from app.modules.audit.service import timeline, to_jsonable, verify_chain
from app.modules.erp_outbox import service as outbox
from app.modules.insights import service as insights
from app.modules.invoices.service import VIEW_ROLES, load_invoice
from app.modules.procurement import service as procurement
from app.modules.review import service as review
from app.modules.rules import service as rules
from app.modules.workflows import budgets
from app.modules.workflows import router as _workflow_sections  # noqa: F401  (registers dashboard sections)
from app.modules.workflows import service as workflows
from app.ports.assistant import ToolSpec

LIMIT = 15
_REQUEST_NO = re.compile(r"^\s*(?:PR[-\s]?)?0*(\d{1,7})\s*$", re.IGNORECASE)


def request_ref(r: PurchaseRequest) -> dict[str, str]:
    return {"type": "request", "id": str(r.id), "label": f"PR-{r.number:04d}"}


def invoice_ref(i: Invoice) -> dict[str, str]:
    return {"type": "invoice", "id": str(i.id), "label": i.invoice_no or f"invoice {str(i.id)[:8]}"}


def po_ref(po: PurchaseOrder) -> dict[str, str]:
    return {"type": "po", "id": str(po.id), "label": po.po_number or po.erp_ref}


def _uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(text).strip())
    except ValueError:
        return None


def _names(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(User.id, User.full_name).where(User.org_id == org_id)).all())


class Tools:
    """All tools for one user. Methods return JSON-safe dicts (money as strings)."""

    def __init__(self, db: Session, user: User):
        self.db, self.user = db, user

    # --- lookups that respect the pages' permissions --------------------------------------------------

    def _request(self, text: str) -> PurchaseRequest:
        match = _REQUEST_NO.match(str(text))
        request_id = _uuid(text)
        if match and request_id is None:
            row = self.db.scalar(select(PurchaseRequest.id).where(PurchaseRequest.org_id == self.user.org_id,
                                                                  PurchaseRequest.number == int(match.group(1))))
            request_id = row
        if request_id is None:
            raise NotFound(f"No request {text} that you can see.")
        try:
            return procurement.load_request(self.db, self.user, request_id)
        except NotFound:
            raise NotFound(f"No request {text} that you can see.") from None

    def _invoice(self, text: str) -> Invoice:
        invoice_id = _uuid(text)
        if invoice_id is None:
            invoice_id = self.db.scalar(select(Invoice.id).where(
                Invoice.org_id == self.user.org_id,
                func.upper(Invoice.invoice_no) == str(text).strip().upper()).order_by(Invoice.created_at.desc()).limit(1))
        if invoice_id is None:
            raise NotFound(f"No invoice {text} that you can see.")
        try:
            return load_invoice(self.db, self.user, invoice_id)
        except NotFound:
            raise NotFound(f"No invoice {text} that you can see.") from None

    # --- tools ----------------------------------------------------------------------------------------

    def whats_waiting_on_me(self, _: dict) -> dict:
        out = []
        for task in workflows.my_tasks(self.db, self.user):
            ref_type = "request" if task["kind"] in ("approval", "buyer", "returned") else "invoice"
            ref_id = task["href"].rstrip("/").split("/")[-1]
            out.append({"kind": task["kind"], "title": task["title"], "detail": task["detail"],
                        "waiting_hours": task["age_hours"], "overdue": task["overdue"],
                        "nudged_by": [n["by"] for n in task["nudges"]],
                        "ref": {"type": ref_type, "id": ref_id, "label": task["title"].split(" · ")[0]}})
        return {"tasks": out, "count": len(out)}

    def find_requests(self, args: dict) -> dict:
        query = select(PurchaseRequest).where(PurchaseRequest.org_id == self.user.org_id)
        if self.user.role not in procurement.ORG_WIDE_VIEWERS:
            query = query.where(PurchaseRequest.requested_by == self.user.id)
        if args.get("status"):
            query = query.where(PurchaseRequest.status == str(args["status"]))
        if args.get("text"):
            query = query.where(PurchaseRequest.title.ilike(f"%{str(args['text'])[:80]}%"))
        categories = dict(self.db.execute(select(Category.id, Category.name)
                                          .where(Category.org_id == self.user.org_id)).all())
        rows = []
        for r in self.db.scalars(query.order_by(PurchaseRequest.created_at.desc()).limit(LIMIT)):
            status = workflows.approval_status(self.db, r)
            rows.append({"ref": request_ref(r), "title": r.title, "status": r.status, "amount": r.amount,
                         "category": categories.get(r.category_id), "cost_center": r.cost_center,
                         "waiting_on": status["waiting_on"] if status else None,
                         "overdue": status["overdue"] if status else False})
        return {"requests": rows, "count": len(rows)}

    def get_request(self, args: dict) -> dict:
        r = self._request(args.get("request", ""))
        names = _names(self.db, r.org_id)
        steps = procurement.current_steps(self.db, r)
        category = self.db.get(Category, r.category_id)
        vendor = self.db.get(Vendor, r.vendor_id) if r.vendor_id else None
        events = timeline(self.db, r.org_id, r.id)
        return {
            "ref": request_ref(r), "title": r.title, "status": r.status, "amount": r.amount,
            "category": category.name if category else None, "cost_center": r.cost_center,
            "needed_by": r.needed_by, "requested_by": names.get(r.requested_by),
            "buyer": names.get(r.assigned_buyer_id), "vendor": vendor.name if vendor else None,
            "justification": r.justification,
            "approval_steps": [{"step": s.step, "who": workflows.step_waiting_on(self.db, r, s),
                                "decision": s.decision, "decided_by": names.get(s.approver_id),
                                "decided_at": s.decided_at, "reason": s.reason} for s in steps],
            "waiting": workflows.approval_status(self.db, r),
            "budget": budgets.check(self.db, r.org_id, r.cost_center, r.amount, request_id=r.id),
            "po_draft_in_erp": outbox.status_for(self.db, outbox.outbox_for(self.db, request_id=r.id)),
            "recent_events": [{"action": e["action"], "by": e.get("actor_name"), "at": e["at"]} for e in events[-8:]],
        }

    def find_invoices(self, args: dict) -> dict:
        if self.user.role not in VIEW_ROLES:
            return {"invoices": [], "note": "Your role cannot list invoices; you can open one you were asked about."}
        query = select(Invoice).where(Invoice.org_id == self.user.org_id)
        if args.get("status"):
            query = query.where(Invoice.status == str(args["status"]))
        if args.get("vendor"):
            query = query.where(Invoice.vendor_name.ilike(f"%{str(args['vendor'])[:80]}%"))
        invoices = list(self.db.scalars(query.order_by(Invoice.created_at.desc()).limit(LIMIT)))
        latest = insights.latest_matches(self.db, [i.id for i in invoices])
        return {"invoices": [{"ref": invoice_ref(i), "vendor": i.vendor_name, "status": i.status, "total": i.total,
                              "invoice_date": i.invoice_date,
                              "amount_at_risk": latest[i.id].amount_at_risk if i.id in latest else None}
                             for i in invoices], "count": len(invoices)}

    def get_invoice(self, args: dict) -> dict:
        i = self._invoice(args.get("invoice", ""))
        match = insights.latest_matches(self.db, [i.id]).get(i.id)
        po = self.db.get(PurchaseOrder, i.po_id) if i.po_id else None
        names = _names(self.db, i.org_id)
        lines = self.db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == i.id).order_by(InvoiceLine.line_no))
        approve_refusal = review.decision_refusal(self.db, self.user, i, "approve")
        tasks = self.db.scalars(select(ExceptionTask).where(ExceptionTask.invoice_id == i.id)
                                .order_by(ExceptionTask.created_at))
        return {
            "ref": invoice_ref(i), "vendor": i.vendor_name, "vendor_gstin": i.vendor_gstin, "status": i.status,
            "invoice_date": i.invoice_date, "subtotal": i.subtotal, "cgst": i.cgst, "sgst": i.sgst, "igst": i.igst,
            "total": i.total, "po": po_ref(po) if po else None,
            # Codes and numbers only: the printed descriptions are document text and are not passed on.
            "lines": [{"line": ln.line_no, "item_code": ln.item_code, "hsn": ln.hsn, "qty": ln.qty, "rate": ln.rate,
                       "amount": ln.amount} for ln in lines],
            "match": None if match is None else {
                "outcome": match.outcome, "amount_at_risk": match.amount_at_risk, "risk_score": match.risk_score,
                "rule_set_version": match.rule_set_version,
                "failed_or_warned": [{"code": r.get("code"), "status": r.get("status"), "message": r.get("message"),
                                      "amount_at_risk": r.get("amount_at_risk")}
                                     for r in match.rule_results if r.get("status") in ("fail", "warn")],
                "explanation": match.explanation},
            "decisions": review.decisions_of(self.db, i),
            "questions": [{"asked_by": names.get(t.asked_by), "asked": names.get(t.assigned_to), "question": t.question,
                           "answer": t.answer, "status": t.status} for t in tasks],
            "can_you_approve": approve_refusal is None,
            "why_you_cannot_approve": approve_refusal.message if approve_refusal else None,
            "bill_draft_in_erp": outbox.status_for(self.db, outbox.outbox_for(self.db, invoice_id=i.id)),
        }

    def get_po(self, args: dict) -> dict:
        text = str(args.get("po", "")).strip()
        po_id = _uuid(text)
        query = select(PurchaseOrder).where(PurchaseOrder.org_id == self.user.org_id)
        query = query.where(PurchaseOrder.id == po_id) if po_id else query.where(
            or_(func.upper(PurchaseOrder.po_number) == text.upper(), func.upper(PurchaseOrder.erp_ref) == text.upper()))
        po = self.db.scalar(query.limit(1))
        if po is None:
            raise NotFound(f"No purchase order {text}.")
        vendor = self.db.get(Vendor, po.vendor_id) if po.vendor_id else None
        lines = list(self.db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)))
        received = dict(self.db.execute(select(GrnLine.po_line_id, func.sum(GrnLine.qty_received))
                                        .where(GrnLine.po_line_id.in_([ln.id for ln in lines]))
                                        .group_by(GrnLine.po_line_id)).all()) if lines else {}
        request = self.db.get(PurchaseRequest, po.request_id) if po.request_id else None
        return {"ref": po_ref(po), "vendor": vendor.name if vendor else None, "status": po.status,
                "po_date": po.po_date, "net_total": po.net_total, "tax_total": po.tax_total,
                "grand_total": po.grand_total, "origin": po.origin,
                "request": request_ref(request) if request else None,
                "lines": [{"line": ln.line_no, "item_code": ln.item_code, "qty": ln.qty, "rate": ln.rate,
                           "amount": ln.amount, "received": received.get(ln.id, Decimal("0"))} for ln in lines]}

    def find_vendor(self, args: dict) -> dict:
        name = str(args.get("name", ""))[:80]
        rows = self.db.scalars(select(Vendor).where(Vendor.org_id == self.user.org_id, Vendor.name.ilike(f"%{name}%"))
                               .order_by(Vendor.name).limit(LIMIT))
        return {"vendors": [{"ref": {"type": "vendor", "id": str(v.id), "label": v.name}, "gstin": v.gstin,
                             "state_code": v.state_code} for v in rows]}

    def spend_summary(self, args: dict) -> dict:
        period = args.get("period") if args.get("period") in ("month", "quarter", "all") else "quarter"
        scope = insights.Scope(org_id=self.user.org_id, user_id=self.user.id, role=self.user.role)
        data = insights.summary(self.db, scope, period)
        data["sections"] = {k: v for k, v in data["sections"].items() if k in ("overdue_approvals", "budgets")}
        return data

    def budget_status(self, args: dict) -> dict:
        fy, quarter = budgets.quarter_of(budgets.today_ist())
        if self.user.role == "requester":
            center = str(args.get("cost_center") or "")
            return {"budget": budgets.check(self.db, self.user.org_id, center, Decimal("0"))}
        return {"fiscal_year": fy, "quarter": quarter, "rows": budgets.status_rows(self.db, self.user.org_id, fy, quarter)}

    def get_audit_trail(self, args: dict) -> dict:
        record = str(args.get("record", ""))
        try:
            entity = self._request(record)
            ref = request_ref(entity)
        except NotFound:
            entity = self._invoice(record)
            ref = invoice_ref(entity)
        events = timeline(self.db, self.user.org_id, entity.id)
        return {"ref": ref, "chain_intact": verify_chain(self.db, entity.id),
                "events": [{"seq": e["seq"], "action": e["action"], "by": e.get("actor_name"), "at": e["at"]}
                           for e in events]}

    def payment_status(self, _: dict) -> dict:
        from app.modules.payments import service as payments  # payments imports nothing from the assistant

        if self.user.role not in payments.PAYMENT_ROLES:
            return {"note": "Only finance or an admin can see payments."}
        return {"runs": [{**r, "ref": None} for r in payments.runs_view(self.db, self.user)[:10]],
                "due": payments.eligible_invoices(self.db, self.user)[:15],
                "note": "Payments are simulated: a mock bank pays approved runs; no real money moves."}

    def list_rules(self, _: dict) -> dict:
        data = rules.overview(self.db, self.user)
        data["categories"] = [{k: v for k, v in c.items() if not k.endswith("_id") and k != "id"}
                              for c in data["categories"]]
        data["workflow"] = {"approval_sla_hours": workflows.sla_hours(self.db, self.user.org_id)}
        return data


_TEXT = {"type": "string"}
_SPECS: list[tuple[str, str, dict[str, Any]]] = [
    ("whats_waiting_on_me", "Everything waiting on the person asking: approvals, requests to complete, questions, "
     "invoices to decide; with how long each has waited and whether it is overdue.", {}),
    ("find_requests", "List purchase requests the person can see, newest first. Optional filters: status "
     "(draft, submitted, with_buyer, in_approval, returned, approved, rejected, po_drafted, po_open, cancelled) "
     "and words in the title.", {"status": _TEXT, "text": _TEXT}),
    ("get_request", "One purchase request in full: approval chain and who it waits on, how long, budget effect, "
     "PO draft state, recent history. `request` is a number like PR-0002.", {"request": _TEXT}),
    ("find_invoices", "List invoices, newest first, with status, total and ₹ at risk. Optional filters: status "
     "(needs_review, manual_entry, confirmed, matched, exception, approved, rejected, correction_requested) and "
     "vendor name.", {"status": _TEXT, "vendor": _TEXT}),
    ("get_invoice", "One invoice in full: totals, matching result with every failed check and ₹ at risk, "
     "decisions, open questions, whether the person asking may approve it and why not, bill draft state. "
     "`invoice` is the invoice number.", {"invoice": _TEXT}),
    ("get_po", "One purchase order: vendor, totals, lines with quantity received. `po` is the PO number.",
     {"po": _TEXT}),
    ("find_vendor", "Find vendors by part of the name: GSTIN and state.", {"name": _TEXT}),
    ("spend_summary", "Dashboard numbers for a period (month, quarter or all): open requests, approval times, "
     "invoices on hold and ₹ at risk, exceptions by type, spend by category, cost centre and vendor, overdue "
     "approvals, budgets.", {"period": _TEXT}),
    ("budget_status", "This quarter's budgets by cost centre: budget, committed, invoiced, % used. "
     "Requesters pass their cost_center.", {"cost_center": _TEXT}),
    ("get_audit_trail", "The tamper-evident history of a request (PR-0002) or an invoice (its number), and "
     "whether the hash chain is intact.", {"record": _TEXT}),
    ("payment_status", "Simulated payment runs (status, net, TDS, who prepared and approved) and approved "
     "invoices still to pay. Finance and admins only.", {}),
    ("list_rules", "Every control: approval tiers, category buyers and extra reviewers, segregation of duties, "
     "matching rules and tolerances, the overdue time limit.", {}),
]


def build_tools(db: Session, user: User) -> list[ToolSpec]:
    tools = Tools(db, user)
    specs = []
    for name, description, properties in _SPECS:
        method = getattr(tools, name)
        schema = {"type": "object", "properties": properties, "additionalProperties": False}
        specs.append(ToolSpec(name=name, description=description, parameters=schema,
                              run=lambda args, m=method: to_jsonable(m(args or {}))))
    return specs
