"""The Orrfin Assistant around the model (BUILD_PLAN v2.3 change 25; ADR 0007; PROMPTS Step 23).

What this layer guarantees, whatever the model writes:
- the model gets only read-only tools bound to the person asking (tools.py);
- links in the answer point only at records a tool returned in this turn, and any web address
  the model writes is removed (a supplier could plant one in an invoice);
- every ₹ figure in the answer is checked against the tool results; if one is not there, the
  answer is shown with a warning ("grounded" = False);
- at most QUESTIONS_PER_HOUR questions per person, and every turn is logged in assistant_turns;
- if the model is missing or fails, the answer is "unavailable" and nothing else is affected.
"""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.ai_prompts import ASSISTANT_PROMPT_VERSION, ASSISTANT_SYSTEM
from app.errors import TooManyRequests
from app.models import AssistantTurn, User
from app.modules.assistant.tools import Tools, build_tools
from app.modules.audit.service import to_jsonable
from app.ports.assistant import AssistantUnavailable, Turn
from app.ports.extractor import ExtractorUnavailable

QUESTIONS_PER_HOUR = 30
MAX_HISTORY = 8
MAX_TEXT = 2000
_RUPEES = re.compile(r"₹\s?(-?[\d,]+(?:\.\d+)?)")
_PLAIN_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
HREFS = {"request": "/requests/{id}", "invoice": "/invoices/{id}", "po": "/pos/{id}", "vendor": "/vendors"}
UNAVAILABLE = ("The assistant is unavailable right now. Everything else works as usual: use My tasks, "
               "the dashboard and the record pages.")


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def known_amounts(value: Any, found: set[Decimal] | None = None) -> set[Decimal]:
    """Every number the tools returned: plain decimal strings, numbers, and ₹ figures inside text."""
    found = set() if found is None else found
    if isinstance(value, dict):
        for item in value.values():
            known_amounts(item, found)
    elif isinstance(value, list):
        for item in value:
            known_amounts(item, found)
    elif isinstance(value, bool):
        pass
    elif isinstance(value, int | Decimal):
        found.add(Decimal(value))
    elif isinstance(value, str):
        if _PLAIN_NUMBER.match(value):
            found.add(Decimal(value))
        for match in _RUPEES.findall(value):
            if (amount := _amount(match)) is not None:
                found.add(amount)
    return found


def unmatched_amounts(answer: str, results: list[dict[str, Any]]) -> list[str]:
    """₹ figures in the answer that no tool result contains. Equal values match however written."""
    known = known_amounts(results)
    missing = []
    for text in _RUPEES.findall(answer):
        amount = _amount(text)
        if amount is not None and amount not in known:
            missing.append(f"₹{text}")
    return missing


def collect_refs(value: Any, refs: dict[str, dict[str, str]] | None = None) -> dict[str, dict[str, str]]:
    refs = {} if refs is None else refs
    if isinstance(value, dict):
        ref = value.get("ref")
        if isinstance(ref, dict) and {"type", "id", "label"} <= ref.keys() and ref["type"] in HREFS:
            refs[f"{ref['type']}:{ref['id']}"] = ref
        for item in value.values():
            collect_refs(item, refs)
    elif isinstance(value, list):
        for item in value:
            collect_refs(item, refs)
    return refs


def links_for(answer: str, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Links only to records a tool returned this turn and the answer names."""
    lowered = answer.lower()
    links = []
    for ref in collect_refs(results).values():
        if ref["label"] and ref["label"].lower() in lowered:
            links.append({"type": ref["type"], "label": ref["label"], "href": HREFS[ref["type"]].format(id=ref["id"])})
    return links[:8]


def _check_rate(db: Session, user: User) -> None:
    since = datetime.now(UTC) - timedelta(hours=1)
    asked = db.scalar(select(func.count()).select_from(AssistantTurn).where(
        AssistantTurn.user_id == user.id, AssistantTurn.created_at >= since))
    if asked >= QUESTIONS_PER_HOUR:
        raise TooManyRequests(f"You have asked {QUESTIONS_PER_HOUR} questions in the last hour. Try again later.")


def _page_note(db: Session, user: User, context: dict[str, str] | None) -> str:
    """Tell the model which record is on screen, only if the person may see it."""
    if not context or context.get("type") not in ("request", "invoice") or not context.get("id"):
        return ""
    tools = Tools(db, user)
    try:
        if context["type"] == "request":
            r = tools._request(context["id"])
            return f"(I am looking at request PR-{r.number:04d}.) "
        i = tools._invoice(context["id"])
        return f"(I am looking at invoice {i.invoice_no or i.id}.) "
    except Exception:  # not visible to this person: say nothing about it
        return ""


def ask(db: Session, user: User, question: str, history: list[dict[str, str]] | None,
        context: dict[str, str] | None, assistant: Any) -> dict[str, Any]:
    question = question.strip()[:MAX_TEXT]
    _check_rate(db, user)
    turns = [Turn(role="assistant" if h.get("role") == "assistant" else "user", text=str(h.get("text", ""))[:MAX_TEXT])
             for h in (history or [])[-MAX_HISTORY:] if h.get("text")]
    log = AssistantTurn(org_id=user.org_id, user_id=user.id, question=question,
                        model_id=getattr(assistant, "model_id", "none"), prompt_version=ASSISTANT_PROMPT_VERSION)
    db.add(log)
    if assistant is None:
        log.error = "No assistant model configured (AI_PROVIDER=fake)."
        return {"available": False, "message": UNAVAILABLE}
    full_question = _page_note(db, user, context) + question
    try:
        reply = assistant.run(ASSISTANT_SYSTEM, turns, full_question, build_tools(db, user))
    except (AssistantUnavailable, ExtractorUnavailable) as exc:
        log.error = str(exc)[:2000]
        return {"available": False, "message": UNAVAILABLE}

    results = [call.result for call in reply.tool_calls]
    answer = _URL.sub("[link removed]", reply.answer).strip()
    missing = unmatched_amounts(answer, results)
    log.answer, log.model_id, log.prompt_version = answer, reply.model_id, reply.prompt_version
    log.tool_calls = to_jsonable([{"name": c.name, "arguments": c.arguments} for c in reply.tool_calls])
    log.grounded = not missing
    return {
        "available": True,
        "answer": answer,
        "links": links_for(answer, results),
        "grounded": not missing,
        "unmatched_amounts": missing,
        "warning": (f"Check these figures on the linked pages: {', '.join(missing)} did not come from Orrfin's records."
                    if missing else None),
        "tools_used": [c.name for c in reply.tool_calls],
        "model_id": reply.model_id,
    }
