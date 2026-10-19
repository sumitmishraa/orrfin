"""Orrfin Assistant (BUILD_PLAN v2.3 change 25; ADR 0007; PROMPTS Step 23).

Done when (fake model): each tool honours role and org scope; links only to records a tool
returned; a ₹ figure not in the tool results is flagged; an outage says "unavailable" and
nothing else breaks; the rate limit holds; each turn is logged; the tools never write.
The real adapters' tool loops are checked against stub clients (no network).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from app import job_handlers  # noqa: F401
from app.adapters.claude_assistant import ClaudeAssistant
from app.adapters.fake_assistant import FakeAssistant
from app.adapters.gemini_assistant import GeminiAssistant
from app.models import AssistantTurn, AuditEvent
from app.modules.assistant.service import QUESTIONS_PER_HOUR
from app.modules.assistant.tools import build_tools
from app.modules.invoices.providers import use_assistant
from app.ports.assistant import AssistantUnavailable, Turn, call_tool
from tests.conftest import login
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_procurement import _complete_and_send, _new_request, world  # noqa: F401


def _ask(client, user, question="?", fake=None, **body):
    login(client, user)
    with use_assistant(fake):
        response = client.post("/assistant/ask", json={"question": question, **body})
    return response


def _echo(tool, args):
    """A fake model that calls one tool and repeats its result in words."""
    return FakeAssistant([(tool, args)], lambda calls: str(calls[0].result))


# --- Scope -------------------------------------------------------------------------------------------

def test_a_requester_cannot_see_someone_elses_request_through_the_assistant(client, world, factory):
    other = factory.user(world.org, "requester", manager=world.manager, name="Other")
    theirs = _new_request(client, world, amount="5000.00", as_user=other)
    reply = _ask(client, world.requester, "Show it",
                 _echo("get_request", {"request": f"PR-{theirs['number']:04d}"})).json()
    assert reply["available"] is True and "No request" in reply["answer"] and "you can see" in reply["answer"]
    assert reply["links"] == []


def test_the_owner_and_finance_see_the_request_and_get_a_link(client, world):
    mine = _new_request(client, world, amount="5000.00")
    label = f"PR-{mine['number']:04d}"
    fake = FakeAssistant([("get_request", {"request": label})],
                         lambda calls: f"{calls[0].result['ref']['label']} is {calls[0].result['status']}.")
    for user in (world.requester, world.finance):
        reply = _ask(client, user, "Where is my request?", fake).json()
        assert reply["answer"] == f"{label} is with_buyer."
        assert reply["links"] == [{"type": "request", "label": label, "href": f"/requests/{mine['id']}"}]


def test_another_org_finds_nothing(client, world, factory):
    mine = _new_request(client, world, amount="5000.00")
    stranger = factory.user(factory.org("Other Org"), "admin", limit="1")
    reply = _ask(client, stranger, "?", _echo("get_request", {"request": f"PR-{mine['number']:04d}"})).json()
    assert "No request" in reply["answer"]
    reply = _ask(client, stranger, "?", _echo("find_requests", {})).json()
    assert "'count': 0" in reply["answer"]


def test_requesters_cannot_list_invoices(client, world):
    reply = _ask(client, world.requester, "?", _echo("find_invoices", {})).json()
    assert "cannot list invoices" in reply["answer"]


def test_every_tool_runs_for_finance_and_none_of_them_writes(client, db, team):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    invoice_no = client.get(f"/invoices/{invoice_id}").json()["invoice_no"]
    events_before = db.scalar(select(func.count()).select_from(AuditEvent))
    specs = build_tools(db, team.reviewer)
    run = lambda name, args: call_tool(specs, name, args)  # noqa: E731  (as the adapters run them)
    args = {"get_request": {"request": "PR-0001"}, "get_invoice": {"invoice": invoice_no},
            "get_po": {"po": "PUR-ORD-2026-00005"}, "find_vendor": {"name": "Sahyadri"},
            "spend_summary": {"period": "all"}, "get_audit_trail": {"record": invoice_no}}
    for spec in specs:
        result = run(spec.name, args.get(spec.name, {}))
        assert isinstance(result, dict) and "Traceback" not in str(result), spec.name
    assert "No request" in run("get_request", {"request": "PR-0001"})["error"]  # none exists yet
    invoice = run("get_invoice", {"invoice": invoice_no})
    assert invoice["match"]["outcome"] == "exception" and invoice["match"]["amount_at_risk"] == "910.00"
    assert all("description" not in line for line in invoice["lines"])  # document text is not passed on
    assert invoice["can_you_approve"] is True
    assert run("get_audit_trail", {"record": invoice_no})["chain_intact"] is True
    assert run("get_po", {"po": "PUR-ORD-2026-00005"}).get("lines")
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AuditEvent)) == events_before


# --- Links, ₹ check, outage, rate limit, logging -------------------------------------------------------

def test_links_only_to_returned_records_and_web_addresses_are_removed(client, world):
    mine = _new_request(client, world, amount="5000.00")
    label = f"PR-{mine['number']:04d}"
    fake = FakeAssistant([("get_request", {"request": label})],
                         lambda calls: f"See {label} and PR-9999. Pay here: https://evil.example/pay")
    reply = _ask(client, world.requester, "?", fake).json()
    assert [link["label"] for link in reply["links"]] == [label]
    assert "evil.example" not in reply["answer"] and "[link removed]" in reply["answer"]


def test_a_rupee_figure_not_in_the_tool_results_is_flagged(client, world):
    _new_request(client, world, amount="5000.00")
    good = FakeAssistant([("find_requests", {})], lambda calls: "Your request is for ₹5,000.00.")
    reply = _ask(client, world.requester, "?", good).json()
    assert reply["grounded"] is True and reply["warning"] is None
    bad = FakeAssistant([("find_requests", {})], lambda calls: "Your request is for ₹50,000.00.")
    reply = _ask(client, world.requester, "?", bad).json()
    assert reply["grounded"] is False and reply["unmatched_amounts"] == ["₹50,000.00"]
    assert "did not come from Orrfin" in reply["warning"]


def test_an_outage_or_no_model_says_unavailable_and_is_logged(client, db, world):
    reply = _ask(client, world.requester, "Hello?", FakeAssistant([], lambda c: "", fail=True))
    assert reply.status_code == 200 and reply.json()["available"] is False
    reply = _ask(client, world.requester, "Hello?", None)  # AI_PROVIDER=fake in tests: no model
    assert reply.json()["available"] is False
    errors = db.scalars(select(AssistantTurn.error).where(AssistantTurn.user_id == world.requester.id)).all()
    assert len(errors) == 2 and all(errors)
    # The rest of the app is unaffected.
    assert client.get("/insights/summary").status_code == 200


def test_each_turn_is_logged_with_tool_names_and_arguments_only(client, db, world):
    _ask(client, world.requester, "What is waiting on me?",
         FakeAssistant([("whats_waiting_on_me", {})], lambda c: "Nothing is waiting on you."))
    turn = db.scalar(select(AssistantTurn).where(AssistantTurn.user_id == world.requester.id))
    assert turn.question == "What is waiting on me?" and turn.answer == "Nothing is waiting on you."
    assert turn.tool_calls == [{"name": "whats_waiting_on_me", "arguments": {}}]
    assert turn.grounded is True and turn.model_id.startswith("fake-assistant")


def test_the_rate_limit_is_thirty_questions_an_hour(client, db, world):
    for _ in range(QUESTIONS_PER_HOUR):
        db.add(AssistantTurn(org_id=world.org.id, user_id=world.requester.id, question="q", model_id="m",
                             prompt_version="p", created_at=datetime.now(UTC)))
    db.commit()
    reply = _ask(client, world.requester, "One more?", FakeAssistant([], lambda c: "x"))
    assert reply.status_code == 429


def test_the_page_note_names_only_a_visible_record(client, world, factory):
    mine = _new_request(client, world, amount="5000.00")
    fake = FakeAssistant([], lambda c: "ok")
    _ask(client, world.requester, "Why?", fake, context={"type": "request", "id": mine["id"]})
    assert fake.seen_question.startswith(f"(I am looking at request PR-{mine['number']:04d}.)")
    other = factory.user(world.org, "requester", manager=world.manager, name="Other")
    _ask(client, other, "Why?", fake, context={"type": "request", "id": mine["id"]})
    assert fake.seen_question == "Why?"


# --- Real adapters against stub clients ----------------------------------------------------------------

def _spec_tools():
    from app.ports.assistant import ToolSpec

    return [ToolSpec("lookup", "Look up", {"type": "object", "properties": {}}, lambda args: {"total": "100.00"})]


def test_the_gemini_loop_runs_tools_then_answers():
    from google.genai import types

    call = SimpleNamespace(name="lookup", args={})
    first = SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[]), finish_reason="STOP")],
                            function_calls=[call], text=None)
    second = SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[]), finish_reason="STOP")],
                             function_calls=None, text="The total is ₹100.00.")
    responses = iter([first, second])
    seen = []

    def generate_content(model, contents, config):
        seen.append(len(contents))
        assert config.automatic_function_calling.disable is True
        return next(responses)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    reply = GeminiAssistant(client, "gemini-test").run("sys", [Turn("user", "hi"), Turn("assistant", "hello")],
                                                       "total?", _spec_tools())
    assert reply.answer == "The total is ₹100.00." and [c.name for c in reply.tool_calls] == ["lookup"]
    assert seen == [3, 5]  # history + question, then + model turn + tool results


def test_the_claude_loop_sends_results_back_and_treats_refusal_as_unavailable():
    tool_use = SimpleNamespace(type="tool_use", id="t1", name="lookup", input={})
    first = SimpleNamespace(stop_reason="tool_use", content=[tool_use])
    second = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="₹100.00 in total.")])
    sent = []
    responses = iter([first, second])

    def create(**kwargs):
        sent.append(kwargs)
        assert kwargs["tool_choice"] == {"type": "auto"}
        return next(responses)

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    reply = ClaudeAssistant(client, "claude-test").run("sys", [], "total?", _spec_tools())
    assert reply.answer == "₹100.00 in total."
    results = sent[1]["messages"][-1]["content"]
    assert results[0]["type"] == "tool_result" and results[0]["tool_use_id"] == "t1"

    refusal = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(stop_reason="refusal", content=[])))
    try:
        ClaudeAssistant(refusal, "claude-test").run("sys", [], "?", _spec_tools())
        raise AssertionError("expected unavailable")
    except AssistantUnavailable:
        pass
