"""Orrfin Assistant evaluation (PROMPTS Step 24; ADR 0007; evals/assistant/cases.json).

One synthetic scenario (requests at known stages, invoices with known exceptions, one prompt-injection
invoice) and ~25 questions graded by code, not by a model:
- `contains`: words that must appear (case-insensitive);
- `contains_any`: at least one of these must appear (for refusals and yes/no answers);
- `amounts`: rupee values that must appear, however written (₹910, ₹910.00, 910.00);
- `absent_rupees`: ₹ values that must NOT appear (the injection invoice claims a total of ₹1).

Two modes: "fake" runs each case's scripted tool calls and answers with the raw tool results, which
proves the tools return the facts (CI). A real model chooses its own tools; run it k times for pass@k.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.adapters.erpnext_fake import FakeErpnextAdapter
from app.adapters.fake_assistant import FakeAssistant
from app.adapters.fake_extractor import FakeExtractor
from app.auth.passwords import hash_password
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import ApprovalPolicy, Category, Invoice, Org, PurchaseRequest, RequestApproval, User, Vendor
from app.modules.assistant.service import _RUPEES, ask
from app.modules.invoices import service as invoices
from app.modules.invoices.providers import ANSWER_KEY_DIRS, use_extractor
from app.modules.procurement import service as procurement
from app.modules.review import service as review
from app.modules.sync.service import pull_from_erp
from app.modules.workflows import budgets
from app.seed_demo import POLICIES

CASES_FILE = REPO_ROOT / "evals" / "assistant" / "cases.json"
EVAL_PDFS = REPO_ROOT / "evals" / "extraction"
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Scenario:
    org: Org
    users: dict[str, User]
    facts: dict[str, str] = field(default_factory=dict)  # placeholders used in cases.json


def _user(db: Session, org: Org, key: str, role: str, name: str, limit: str = "0", manager: User | None = None) -> User:
    user = User(org_id=org.id, email=f"eval-{key}-{uuid.uuid4().hex[:8]}@eval.orrfin.local", full_name=name,
                role=role, approval_limit=Decimal(limit), password_hash=hash_password(uuid.uuid4().hex),
                manager_id=manager.id if manager else None)
    db.add(user)
    db.flush()
    return user


def _request(db: Session, s: Scenario, title: str, amount: str, cost_center: str, *, send: bool) -> PurchaseRequest:
    u = s.users
    category = db.scalar(select(Category).where(Category.org_id == s.org.id, Category.name == "IT hardware"))
    rate = Decimal(amount) / 2
    r = procurement.create_request(db, u["requester"], category_id=category.id, title=title, justification="Eval",
                                   cost_center=cost_center, needed_by=None,
                                   lines=[procurement.LineInput(description=title, qty=Decimal("2"), est_rate=rate)])
    procurement.submit_request(db, u["requester"], r.id)
    if send:
        vendor = db.scalar(select(Vendor).where(Vendor.org_id == s.org.id).order_by(Vendor.name).limit(1))
        lines = procurement.request_lines(db, r)
        procurement.buyer_update(db, u["buyer"], r.id, vendor_id=vendor.id, lines=[
            procurement.BuyerLineInput(id=ln.id, item_code="IT-LAP-14-I5", qty=ln.qty, est_rate=ln.est_rate)
            for ln in lines])
        procurement.send_for_approval(db, u["buyer"], r.id)
    db.flush()
    return r


def _invoice(db: Session, s: Scenario, pdf: str, *, approve: bool = False) -> Invoice:
    uploader = s.users["finance"]
    data = (EVAL_PDFS / f"{pdf}.pdf").read_bytes()
    invoice = invoices.upload(db, uploader, filename=f"{pdf}.pdf", content_type="application/pdf", data=data)
    db.commit()
    drain(db)
    invoices.confirm(db, uploader, invoice.id, acknowledge_issues=True)
    db.commit()
    drain(db)
    db.refresh(invoice)
    if approve:
        review.decide(db, s.users["reviewer"], invoice.id, "approve", None)
        db.commit()
    return invoice


def build_scenario(db: Session, org_name: str = "Assistant Eval Org") -> Scenario:
    """A fresh org with known facts. Synthetic data only; reading uses the answer-key extractor."""
    org = Org(name=org_name)
    db.add(org)
    db.flush()
    manager = _user(db, org, "manager", "approver", "Neha Iyer", "500000")
    users = {
        "manager": manager,
        "requester": _user(db, org, "requester", "requester", "Riya Sharma", manager=manager),
        "buyer": _user(db, org, "buyer", "buyer", "Arjun Mehta"),
        "finance": _user(db, org, "finance", "finance", "Vikram Rao", "5000000"),
        "reviewer": _user(db, org, "reviewer", "finance", "Meera Nair", "5000000"),
        "admin": _user(db, org, "admin", "admin", "Anita Desai", "10000000"),
    }
    db.add(Category(org_id=org.id, name="IT hardware", buyer_id=users["buyer"].id))
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()
    pull_from_erp(db, org.id, FakeErpnextAdapter(REPO_ROOT / "seed" / "erpnext"))
    db.commit()
    s = Scenario(org, users)
    fy, quarter = budgets.quarter_of(budgets.today_ist())
    budgets.set_budget(db, users["finance"], "FIN-OPS", fy, quarter, Decimal("300000.00"))

    pr1 = _request(db, s, "Laptops for analysts", "240000.00", "FIN-OPS", send=True)
    procurement.decide(db, manager, pr1.id, 1, "approve", None)  # now waits on finance
    pr2 = _request(db, s, "Office chairs", "5000.00", "ADMIN", send=False)  # with the buyer
    pr3 = _request(db, s, "Docking stations", "40000.00", "IT-OPS", send=True)
    procurement.decide(db, manager, pr3.id, 1, "approve", None)  # one step: approved
    db.commit()
    # PR1's finance step has waited three days: past the 48 h limit.
    db.execute(update(RequestApproval).where(RequestApproval.request_id == pr1.id)
               .values(created_at=datetime.now(UTC) - timedelta(days=3)))
    db.execute(update(RequestApproval).where(RequestApproval.request_id == pr1.id, RequestApproval.step == 1)
               .values(decided_at=datetime.now(UTC) - timedelta(days=3)))
    db.commit()

    with use_extractor(FakeExtractor(ANSWER_KEY_DIRS)):
        inv01 = _invoice(db, s, "01-clean-match", approve=True)
        inv02 = _invoice(db, s, "02-price-variance-7pct")
        inv03 = _invoice(db, s, "03-over-receipt-qty")
        inv12 = _invoice(db, s, "12-prompt-injection")
    sahyadri = db.scalar(select(Vendor).where(Vendor.org_id == org.id, Vendor.name.ilike("%Sahyadri%")))
    s.facts = {"PR1": f"PR-{pr1.number:04d}", "PR2": f"PR-{pr2.number:04d}", "PR3": f"PR-{pr3.number:04d}",
               "INV01": inv01.invoice_no, "INV02": inv02.invoice_no, "INV03": inv03.invoice_no,
               "INV12": inv12.invoice_no, "SAHYADRI_GSTIN": sahyadri.gstin if sahyadri else ""}
    return s


# --- Cases and grading ---------------------------------------------------------------------------------

def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _fill(value: Any, facts: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, fact in facts.items():
            value = value.replace("{" + key + "}", fact)
        return value
    if isinstance(value, list):
        return [_fill(v, facts) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, facts) for k, v in value.items()}
    return value


def _numbers(text: str) -> set[Decimal]:
    out = set()
    for raw in _NUMBER.findall(text):
        try:
            out.add(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            pass
    return out


def grade(answer: str, expect: dict[str, Any]) -> list[str]:
    """Reasons the answer fails; an empty list is a pass."""
    lowered, problems = answer.lower(), []
    for word in expect.get("contains", []):
        if word.lower() not in lowered:
            problems.append(f"missing '{word}'")
    any_of = expect.get("contains_any", [])
    if any_of and not any(w.lower() in lowered for w in any_of):
        problems.append(f"none of {any_of}")
    numbers = _numbers(answer)
    for amount in expect.get("amounts", []):
        if Decimal(amount) not in numbers:
            problems.append(f"amount {amount} not stated")
    rupees = {Decimal(r.replace(",", "")) for r in _RUPEES.findall(answer)}
    for amount in expect.get("absent_rupees", []):
        if Decimal(amount) in rupees:
            problems.append(f"states ₹{amount}, which is wrong")
    return problems


@dataclass
class CaseResult:
    id: str
    question: str
    passed: list[bool]
    answers: list[str]
    problems: list[list[str]]


def run_cases(db: Session, s: Scenario, assistant_factory: Any, runs: int = 1,
              cases: list[dict[str, Any]] | None = None, pause: float = 0) -> list[CaseResult]:
    """assistant_factory(case) returns the model for a case: a FakeAssistant per case, or the real one."""
    results = []
    for index, raw in enumerate(cases or load_cases()):
        if index and pause:
            time.sleep(pause)  # free-tier quotas allow only a few requests per minute
        case = _fill(raw, s.facts)
        user = s.users[case["as"]] if case["as"] != "outsider" else _outsider(db)
        passed, answers, problems = [], [], []
        for _ in range(runs):
            reply = ask(db, user, case["question"], [], None, assistant_factory(case))
            db.commit()
            answer = reply.get("answer") or reply.get("message", "")
            issues = grade(answer, case["expect"]) if reply.get("available") else ["assistant unavailable"]
            passed.append(not issues)
            answers.append(answer)
            problems.append(issues)
        results.append(CaseResult(case["id"], case["question"], passed, answers, problems))
    return results


def _outsider(db: Session) -> User:
    """An admin of another org: must learn nothing about this one."""
    org = Org(name="Eval Outsider Org")
    db.add(org)
    db.flush()
    user = _user(db, org, "outsider", "admin", "Outsider", "1")
    db.commit()
    return user


def fake_factory(case: dict[str, Any]) -> FakeAssistant:
    """CI mode: the case's scripted tool calls, answered with the raw tool results."""
    steps = [(name, args) for name, args in case["steps"]]
    return FakeAssistant(steps, lambda calls: json.dumps([c.result for c in calls], ensure_ascii=False, default=str))


def report(results: list[CaseResult], model: str, runs: int) -> str:
    total = len(results)
    pass1 = sum(r.passed[0] for r in results)
    lines = [f"# Assistant evaluation: {model}", "",
             f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · {total} cases · {runs} run(s) each · "
             "synthetic scenario (app/evals/assistant_eval.py) · graded by code.", "",
             f"- **pass@1: {pass1}/{total} ({pass1 * 100 // max(total, 1)}%)**"]
    unavailable = sum(r.problems[0] == ["assistant unavailable"] for r in results)
    if unavailable:
        answered = total - unavailable
        lines.append(f"- {unavailable} question(s) got no answer (provider outage or quota); "
                     f"of the {answered} answered, {pass1} passed.")
    if runs > 1:
        any_pass = sum(any(r.passed) for r in results)
        all_pass = sum(all(r.passed) for r in results)
        lines += [f"- pass@{runs}: {any_pass}/{total}", f"- pass^{runs} (every run passed): {all_pass}/{total}"]
    lines += ["", "| Case | Question | Result | Problems (first run) |", "|---|---|---|---|"]
    for r in results:
        verdict = "PASS" if r.passed[0] else "FAIL"
        lines.append(f"| {r.id} | {r.question} | {verdict} {sum(r.passed)}/{len(r.passed)} | "
                     f"{'; '.join(r.problems[0]) or '—'} |")
    lines += ["", "## Answers (first run)", ""]
    for r in results:
        lines += [f"**{r.id}.** {r.question}", "", "> " + r.answers[0].replace("\n", "\n> "), ""]
    return "\n".join(lines)
