"""Superagents: named groups of tools, each for one job, on one assistant (BUILD_PLAN change 47).

Every tool is bound to the person asking (their role, their org), exactly like the pages. Read tools
come from the existing assistant (modules/assistant/tools.py). Propose tools only store a proposal
for that person to submit; none of them changes a business record.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Forbidden, Invalid
from app.models import Category, User
from app.modules.agents import proposals, workflow_builder
from app.modules.assistant.tools import build_tools
from app.modules.audit.service import to_jsonable
from app.ports.assistant import ToolSpec

_TEXT = {"type": "string"}
_LINES = {"type": "array", "items": {"type": "object", "properties": {"description": _TEXT, "qty": _TEXT,
                                                                       "est_rate": _TEXT}}}

SUPERAGENTS: dict[str, dict[str, Any]] = {
    "concierge": {"title": "Procurement concierge", "summary": "Answers anything you can see, and drafts requests.",
                  "read": "*", "propose": ["propose_request", "propose_supplier_invite", "propose_rfq"]},
    "intake": {"title": "Intake agent", "summary": "Turns a need into a draft purchase request.",
               "read": ["find_requests", "get_request", "budget_status", "list_rules"], "propose": ["propose_request"]},
    "invoice": {"title": "Invoice agent", "summary": "Explains invoice checks, exceptions and their trail.",
                "read": ["find_invoices", "get_invoice", "get_po", "get_audit_trail", "find_vendor"], "propose": []},
    "sourcing": {"title": "Sourcing agent", "summary": "Finds vendors and drafts RFQs and supplier invitations.",
                 "read": ["find_vendor", "spend_summary"], "propose": ["propose_rfq", "propose_supplier_invite"]},
    "workflow": {"title": "Workflow builder", "summary": "Drafts an approval workflow from plain words.",
                 "read": ["list_rules"], "propose": ["propose_workflow"]},
    "finance": {"title": "Finance agent", "summary": "Budgets, spend and simulated payment status.",
                "read": ["spend_summary", "budget_status", "payment_status", "whats_waiting_on_me"], "propose": []},
}


def _category_id(db: Session, user: User, name: str) -> uuid.UUID:
    found = db.scalar(select(Category.id).where(Category.org_id == user.org_id,
                                                func.lower(Category.name) == (name or "").strip().lower()))
    if found is None:
        names = ", ".join(db.scalars(select(Category.name).where(Category.org_id == user.org_id)))
        raise Invalid(f"No category called {name!r}. Categories: {names}.")
    return found


def _propose_tools(db: Session, user: User, agent: str) -> dict[str, ToolSpec]:
    def card(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"proposal": to_jsonable(proposals.as_card(proposals.create(db, user, kind, payload, agent))),
                "note": "Shown to the person as a card. Nothing has been created; they submit it themselves."}

    def propose_request(a: dict[str, Any]) -> dict[str, Any]:
        return card("request", {"category_id": _category_id(db, user, a.get("category", "")), "title": a.get("title", ""),
                                "justification": a.get("justification", ""), "cost_center": a.get("cost_center", ""),
                                "lines": a.get("lines") or []})

    def propose_supplier_invite(a: dict[str, Any]) -> dict[str, Any]:
        return card("supplier_invite", {k: a.get(k, "") for k in ("legal_name", "country", "category", "contact_name",
                                                                   "contact_email")})

    def propose_rfq(a: dict[str, Any]) -> dict[str, Any]:
        return card("rfq", {"title": a.get("title", ""), "category_id": _category_id(db, user, a.get("category", "")),
                            "currency": a.get("currency") or "INR", "closes_in_days": int(a.get("closes_in_days") or 7),
                            "lines": [{"description": l.get("description", ""), "qty": l.get("qty", "1")}
                                      for l in a.get("lines") or []]})

    def propose_workflow(a: dict[str, Any]) -> dict[str, Any]:
        if user.role != "admin":
            raise Forbidden("Only an admin can draft a workflow.")
        result = workflow_builder.draft(db, user.org_id, a.get("description", ""))
        if result["problems"]:
            return {"problems": result["problems"], "not_understood": result["not_understood"]}
        return {**card("workflow_draft", {"definition": result["definition"]}), "previews": result["previews"]}

    specs = [
        ("propose_request", "Draft a purchase request for the person to check and submit. category is a category "
         "name; lines need description, qty and est_rate as plain numbers in text.",
         {"category": _TEXT, "title": _TEXT, "justification": _TEXT, "cost_center": _TEXT, "lines": _LINES}, propose_request),
        ("propose_supplier_invite", "Draft an invitation for a new supplier (country IN or AE; category goods, "
         "services or software).", {k: _TEXT for k in ("legal_name", "country", "category", "contact_name",
                                                        "contact_email")}, propose_supplier_invite),
        ("propose_rfq", "Draft a request for quotation (a category name, lines with description and qty).",
         {"title": _TEXT, "category": _TEXT, "currency": _TEXT, "closes_in_days": _TEXT, "lines": _LINES}, propose_rfq),
        ("propose_workflow", "Draft an approval workflow from a plain-words description. Admins only. "
         "It is only a draft: an admin saves and publishes it on the workflow page.", {"description": _TEXT},
         propose_workflow),
    ]
    return {name: ToolSpec(name=name, description=description,
                           parameters={"type": "object", "properties": props, "additionalProperties": False},
                           run=fn) for name, description, props, fn in specs}


def tools_for(db: Session, user: User, agent: str) -> list[ToolSpec]:
    """The tools of one superagent, bound to this person. An unknown agent has no tools."""
    spec = SUPERAGENTS.get(agent)
    if spec is None:
        raise Invalid(f"Unknown agent. Choose one of: {', '.join(SUPERAGENTS)}.")
    read = build_tools(db, user)
    if spec["read"] != "*":
        read = [t for t in read if t.name in spec["read"]]
    propose = _propose_tools(db, user, agent)
    return read + [propose[name] for name in spec["propose"]]
