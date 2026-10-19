"""Workflow automations and budgets (BUILD_PLAN v2.4 changes 29–30; PROMPTS Step 22).

Done when: overdue and nudges work and are audited; an open exception task blocks approval and
its assignee can never approve; the category's extra step needs its named person; budget maths
is right and only warns; settings and budgets are edited only by the right roles.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app import job_handlers  # noqa: F401
from app.models import AuditEvent, ExceptionTask, RequestApproval
from app.modules.workflows.budgets import quarter_of, today_ist
from tests.conftest import login
from tests.integration.test_invoice_review import _decide as decide_invoice
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_procurement import _complete_and_send, _decide, _new_request, world  # noqa: F401


# --- Extra approval step by category ------------------------------------------------------------------

def _add_security_step(client, world, factory):
    security = factory.user(world.org, "approver", limit="0", name="Security lead")
    login(client, world.admin)
    response = client.patch(f"/rules/categories/{world.category.id}",
                            json={"extra_approver_id": str(security.id), "extra_step_label": "IT security review"})
    assert response.status_code == 200, response.text
    return security


def test_a_category_adds_a_named_step_that_only_that_person_can_decide(client, db, world, factory):
    security = _add_security_step(client, world, factory)
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    steps = request["current_steps"]
    assert [(s["required_role"], s["step_label"]) for s in steps] == [("manager", None),
                                                                      ("category_reviewer", "IT security review")]
    assert _decide(client, world.manager, request["id"], 1).status_code == 200
    # Finance holds a high limit but is not the named reviewer.
    refused = _decide(client, world.finance, request["id"], 2)
    assert refused.status_code == 403 and "Security lead" in refused.json()["detail"]
    # The named reviewer approves although their spending limit is ₹0: a review is not a spend approval.
    approved = _decide(client, security, request["id"], 2)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


def test_a_category_change_never_alters_a_running_chain(client, db, world, factory):
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    _add_security_step(client, world, factory)
    roles = db.scalars(select(RequestApproval.required_role).where(RequestApproval.request_id == request["id"])).all()
    assert roles == ["manager"]


def test_the_extra_approver_must_be_more_than_a_requester_and_the_step_needs_a_name(client, world):
    login(client, world.admin)
    assert client.patch(f"/rules/categories/{world.category.id}",
                        json={"extra_approver_id": str(world.requester.id), "extra_step_label": "X"}).status_code == 422
    assert client.patch(f"/rules/categories/{world.category.id}",
                        json={"extra_approver_id": str(world.finance.id)}).status_code == 422


# --- My tasks, overdue and nudges ---------------------------------------------------------------------

def _make_overdue(db, request_id: str, hours: int = 72) -> None:
    db.execute(update(RequestApproval).where(RequestApproval.request_id == request_id)
               .values(created_at=datetime.now(UTC) - timedelta(hours=hours)))
    db.commit()


def test_an_approver_sees_their_task_and_it_turns_overdue_after_the_sla(client, db, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    login(client, world.manager)
    tasks = client.get("/tasks").json()
    task = next(t for t in tasks if t["id"] == request["id"])
    assert task["kind"] == "approval" and task["overdue"] is False
    assert "Requester's manager (Manager)" in task["detail"]
    assert f"/requests/{request['id']}" in task["whatsapp"] and "never approves from chat" in task["whatsapp"]

    _make_overdue(db, request["id"])
    task = next(t for t in client.get("/tasks").json() if t["id"] == request["id"])
    assert task["overdue"] is True
    # The requester has nothing to approve, so no approval task for them.
    login(client, world.requester)
    assert all(t["kind"] != "approval" for t in client.get("/tasks").json())


def test_a_nudge_is_audited_rate_limited_and_only_for_overdue_steps(client, db, world, factory):
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    login(client, world.requester)
    assert client.post(f"/requests/{request['id']}/nudge").status_code == 409  # not overdue yet

    _make_overdue(db, request["id"])
    assert client.get(f"/requests/{request['id']}/reminders").json()["can_nudge"] is True
    sent = client.post(f"/requests/{request['id']}/nudge")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"]["nudges"][0]["by"] == "Requester"
    assert client.post(f"/requests/{request['id']}/nudge").status_code == 409  # cooldown
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == request["id"], AuditEvent.action == "nudged"))
    assert event.payload["step"] == 1 and event.actor_id == world.requester.id

    outsider = factory.user(world.org, "approver", limit="1", name="Outsider")
    login(client, outsider)
    assert client.post(f"/requests/{request['id']}/nudge").status_code == 403
    # The nudge shows on the approver's task.
    login(client, world.manager)
    task = next(t for t in client.get("/tasks").json() if t["id"] == request["id"])
    assert [n["by"] for n in task["nudges"]] == ["Requester"]


def test_the_sla_setting_is_admin_only_and_bounded(client, world):
    login(client, world.finance)
    assert client.put("/settings/workflow", json={"approval_sla_hours": 24}).status_code == 403
    login(client, world.admin)
    assert client.put("/settings/workflow", json={"approval_sla_hours": 0}).status_code == 422
    assert client.put("/settings/workflow", json={"approval_sla_hours": 24}).status_code == 200
    assert client.get("/settings/workflow").json()["approval_sla_hours"] == 24


def test_overdue_approvals_appear_on_the_dashboard(client, db, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    _make_overdue(db, request["id"])
    login(client, world.finance)
    section = client.get("/insights/summary", params={"period": "all"}).json()["sections"]["overdue_approvals"]
    assert section["count"] == 1 and section["rows"][0]["number"].startswith("PR-")


# --- Exception tasks ----------------------------------------------------------------------------------

def test_a_question_holds_the_invoice_until_answered(client, db, team, factory):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    asked = factory.user(team.org, "requester", name="Asked requester")
    login(client, asked)
    assert client.get(f"/invoices/{invoice_id}").status_code == 403  # requesters can't open invoices…

    login(client, team.reviewer)
    held = client.post(f"/invoices/{invoice_id}/questions",
                       json={"assigned_to": str(asked.id), "question": "Did we agree the higher price?"})
    assert held.status_code == 200, held.text
    view = held.json()["exception_tasks"]
    assert view["tasks"][0]["status"] == "open" and view["tasks"][0]["assigned_to"] == "Asked requester"
    blocked = decide_invoice(client, team.reviewer, invoice_id, reason="Agreed by phone")
    assert blocked.status_code == 409 and "Asked requester" in blocked.json()["detail"]

    # …but the person asked can open this one, sees it in their tasks, and answers.
    login(client, asked)
    assert client.get(f"/invoices/{invoice_id}").status_code == 200
    task = next(t for t in client.get("/tasks").json() if t["kind"] == "exception_task")
    answered = client.post(f"/exception-tasks/{task['id']}/answer", json={"answer": "Yes, new price from October."})
    assert answered.status_code == 200 and answered.json()["exception_tasks"]["tasks"][0]["status"] == "answered"

    login(client, team.reviewer)
    assert any(t["kind"] == "answer" for t in client.get("/tasks").json())
    assert decide_invoice(client, team.reviewer, invoice_id, reason="Price agreed, see answer").status_code == 200
    statuses = db.scalars(select(ExceptionTask.status).where(ExceptionTask.invoice_id == invoice_id)).all()
    assert statuses == ["closed"]
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == invoice_id)
                         .order_by(AuditEvent.seq)).all()
    assert ["question_asked", "question_answered", "decision_approve", "questions_closed"] == \
        [a for a in actions if a in ("question_asked", "question_answered", "decision_approve", "questions_closed")]


def test_the_person_asked_can_never_approve_that_invoice(client, db, team, factory):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    colleague = factory.user(team.org, "finance", limit="5000000", name="Colleague")
    login(client, team.reviewer)
    client.post(f"/invoices/{invoice_id}/questions", json={"assigned_to": str(colleague.id), "question": "OK?"})
    login(client, colleague)
    task_id = next(t for t in client.get("/tasks").json() if t["kind"] == "exception_task")["id"]
    assert client.post(f"/exception-tasks/{task_id}/answer", json={"answer": "Looks fine"}).status_code == 200
    refused = decide_invoice(client, colleague, invoice_id, reason="fine")
    assert refused.status_code == 403 and "asked about this invoice" in refused.json()["detail"]


def test_only_finance_or_admin_ask_and_only_the_assignee_answers(client, db, team, factory):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    buyer = factory.user(team.org, "buyer", name="Buyer")
    login(client, buyer)
    assert client.post(f"/invoices/{invoice_id}/questions",
                       json={"assigned_to": str(team.reviewer.id), "question": "?"}).status_code == 403
    login(client, team.reviewer)
    assert client.post(f"/invoices/{invoice_id}/questions",
                       json={"assigned_to": str(team.reviewer.id), "question": "?"}).status_code == 422  # self
    client.post(f"/invoices/{invoice_id}/questions", json={"assigned_to": str(buyer.id), "question": "Received?"})
    task_id = db.scalar(select(ExceptionTask.id).where(ExceptionTask.invoice_id == invoice_id))
    assert client.post(f"/exception-tasks/{task_id}/answer", json={"answer": "x"}).status_code == 404  # not theirs


# --- Budgets ------------------------------------------------------------------------------------------

def test_budget_maths_warns_but_never_blocks(client, db, world):
    fy, quarter = quarter_of(today_ist())
    login(client, world.requester)
    assert client.put("/budgets", json={"cost_center": "FIN-OPS", "fiscal_year": fy, "quarter": quarter,
                                        "amount": "300000.00"}).status_code == 403
    login(client, world.finance)
    assert client.put("/budgets", json={"cost_center": "fin-ops", "fiscal_year": "2026-28", "quarter": quarter,
                                        "amount": "1.00"}).status_code == 422
    saved = client.put("/budgets", json={"cost_center": "fin-ops", "fiscal_year": fy, "quarter": quarter,
                                         "amount": "300000.00"})
    assert saved.status_code == 200 and saved.json()["rows"][0]["cost_center"] == "FIN-OPS"

    login(client, world.requester)
    check = client.get("/budgets/check", params={"cost_center": "FIN-OPS", "amount": "240000.00"}).json()
    assert check["committed"] == "0" and check["pct_after"] == "80.0" and check["over"] is False

    request = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))  # in approval
    login(client, world.requester)
    over = client.get("/budgets/check", params={"cost_center": "FIN-OPS", "amount": "100000.00"}).json()
    assert over["committed"] == "240000.00" and over["over"] is True and "₹40,000.00 over budget" in over["message"]
    # Checked for the request itself, it does not count against itself.
    own = client.get("/budgets/check", params={"request_id": request["id"]}).json()
    assert own["committed"] == "0" and own["pct_after"] == "80.0"
    # Over budget is a warning only: a second request still goes into approval.
    second = _complete_and_send(client, world, _new_request(client, world, amount="100000.00"))
    assert second["status"] == "in_approval"

    login(client, world.finance)
    rows = client.get("/budgets").json()["rows"]
    assert rows[0]["committed"] == "340000.00" and rows[0]["over"] is True
    section = client.get("/insights/summary").json()["sections"]["budgets"]
    assert section["rows"][0]["pct_used"] == "113.3"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "budget_set")) is not None


def test_no_budget_means_no_warning(client, world):
    login(client, world.requester)
    assert client.get("/budgets/check", params={"cost_center": "NOPE", "amount": "5.00"}).json() is None


def test_quarters_follow_the_april_march_year():
    from datetime import date

    from app.modules.workflows.budgets import quarter_bounds

    assert quarter_of(date(2026, 10, 18)) == ("2026-27", 3)
    assert quarter_of(date(2027, 2, 1)) == ("2026-27", 4)
    assert quarter_of(date(2026, 4, 1)) == ("2026-27", 1)
    start, end = quarter_bounds("2026-27", 4)
    assert start.isoformat() == "2026-12-31T18:30:00+00:00" and end.isoformat() == "2027-03-31T18:30:00+00:00"
    start, end = quarter_bounds("2026-27", 3)
    assert end.isoformat() == "2026-12-31T18:30:00+00:00"
