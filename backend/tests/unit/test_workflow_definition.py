"""Workflow definitions: what may be published, and which route a record takes (ADR 0010, BUILD_PLAN §11 M9).

Pure tests: no database. The safety properties matter most: a definition that could loop,
strand a request, or let it finish with nobody approving must never validate.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.workflow_engine.definition import validate
from app.modules.workflow_engine.evaluate import NAMED_REVIEWER_STEP, approval_steps, route

SECURITY_LEAD = str(uuid.uuid4())


def tiered() -> dict:
    """Manager always; finance above ₹50,000; a named security lead for software."""
    return {
        "subject": "request",
        "start": "mgr",
        "nodes": [
            {"id": "mgr", "kind": "approval", "role": "manager", "next": "big"},
            {"id": "big", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": "50000.00"}, "then": "fin", "else": "soft"},
            {"id": "fin", "kind": "approval", "role": "finance", "label": "Finance approval", "next": "soft"},
            {"id": "soft", "kind": "condition",
             "when": {"field": "category", "op": "in", "value": ["Software & SaaS"]}, "then": "sec", "else": "end"},
            {"id": "sec", "kind": "approval", "approver_id": SECURITY_LEAD, "label": "IT security review",
             "next": "end"},
        ],
    }


def roles(definition: dict, **facts) -> list[str]:
    return [step["role"] for step in approval_steps(definition, facts)]


# --- A good definition ----------------------------------------------------------------------

def test_a_well_formed_workflow_has_no_problems():
    assert validate(tiered()) == []


def test_the_route_follows_the_amount_and_the_category():
    workflow = tiered()

    assert roles(workflow, amount=Decimal("40000.00"), category="IT hardware") == ["manager"]
    assert roles(workflow, amount=Decimal("200000.00"), category="IT hardware") == ["manager", "finance"]
    assert roles(workflow, amount=Decimal("40000.00"), category="software & saas ") == \
        ["manager", NAMED_REVIEWER_STEP]


def test_the_boundary_amount_is_compared_exactly():
    workflow = tiered()

    assert roles(workflow, amount=Decimal("50000.00"), category="x") == ["manager"]
    assert roles(workflow, amount=Decimal("50000.01"), category="x") == ["manager", "finance"]


def test_a_named_person_step_carries_that_person_and_its_label():
    step = approval_steps(tiered(), {"amount": Decimal("1.00"), "category": "Software & SaaS"})[-1]

    assert step == {"role": NAMED_REVIEWER_STEP, "label": "IT security review",
                    "approver_id": uuid.UUID(SECURITY_LEAD)}


def test_the_same_facts_always_give_the_same_route():
    facts = {"amount": Decimal("75000.00"), "category": "Software & SaaS"}

    assert route(tiered(), facts) == route(tiered(), facts)


def test_a_missing_fact_makes_its_rule_false_rather_than_failing():
    assert roles(tiered(), category="IT hardware") == ["manager"]


def test_all_and_any_combine_rules():
    workflow = {
        "subject": "request", "start": "c",
        "nodes": [
            {"id": "c", "kind": "condition", "then": "fin", "else": "mgr",
             "when": {"all": [{"field": "amount", "op": ">=", "value": "1000"},
                              {"any": [{"field": "cost_center", "op": "==", "value": "IT-OPS"},
                                       {"field": "custom.urgent", "op": "==", "value": "yes"}]}]}},
            {"id": "fin", "kind": "approval", "role": "finance", "next": "end"},
            {"id": "mgr", "kind": "approval", "role": "manager", "next": "end"},
        ],
    }

    assert validate(workflow) == []
    assert roles(workflow, amount=Decimal("1000"), cost_center="it-ops") == ["finance"]
    assert roles(workflow, amount=Decimal("1000"), cost_center="HR", **{"custom.urgent": "Yes"}) == ["finance"]
    assert roles(workflow, amount=Decimal("999.99"), cost_center="IT-OPS") == ["manager"]


# --- Definitions that must never be published ------------------------------------------------

def test_a_route_that_ends_with_no_approval_is_refused():
    workflow = tiered()
    workflow["start"] = "big"  # skips the manager: a small non-software request would approve itself

    problems = validate(workflow)

    assert any("no approval" in problem for problem in problems)


def test_a_loop_is_refused():
    workflow = tiered()
    workflow["nodes"][-1]["next"] = "mgr"

    assert any("cannot loop" in problem for problem in validate(workflow))


def test_a_step_nothing_leads_to_is_refused():
    workflow = tiered()
    workflow["nodes"].append({"id": "orphan", "kind": "approval", "role": "admin", "next": "end"})

    assert validate(workflow) == ['Step "orphan" can never be reached.']


def test_an_arrow_to_a_step_that_does_not_exist_is_refused():
    workflow = tiered()
    workflow["nodes"][0]["next"] = "nowhere"

    assert any('"nowhere" does not exist' in problem for problem in validate(workflow))


@pytest.mark.parametrize("role", ["requester", "buyer", "superuser"])
def test_only_approving_roles_may_approve(role):
    workflow = tiered()
    workflow["nodes"][0]["role"] = role

    assert any("cannot approve" in problem for problem in validate(workflow))


def test_an_approval_cannot_name_both_a_role_and_a_person():
    workflow = tiered()
    workflow["nodes"][0]["approver_id"] = SECURITY_LEAD

    assert any("either a role or one named person" in problem for problem in validate(workflow))


@pytest.mark.parametrize("when, expected", [
    ({"field": "password_hash", "op": "==", "value": "x"}, "is not a field"),
    ({"field": "amount", "op": "matches", "value": "1"}, "is not a comparison"),
    ({"field": "amount", "op": ">", "value": 50000.5}, "in quotes"),
    ({"field": "amount", "op": ">", "value": "lots"}, "in quotes"),
    ({"field": "category", "op": ">", "value": "A"}, "is text"),
    ({"field": "category", "op": "in", "value": "Software"}, "needs a list"),
    ({"field": "amount", "op": ">", "value": "1", "run": "import os"}, 'exactly "field", "op" and "value"'),
])
def test_conditions_accept_only_known_fields_operators_and_exact_values(when, expected):
    workflow = tiered()
    workflow["nodes"][1]["when"] = when

    assert any(expected in problem for problem in validate(workflow))


def test_two_steps_cannot_share_a_name_and_end_is_reserved():
    duplicate = tiered()
    duplicate["nodes"][2]["id"] = "mgr"
    reserved = tiered()
    reserved["nodes"][0]["id"] = "end"

    assert validate(duplicate) == ['Two steps are both named "mgr".']
    assert "reserved" in validate(reserved)[0]


@pytest.mark.parametrize("definition", [None, [], "workflow", {"subject": "invoice_payment", "nodes": []},
                                        {"subject": "request", "nodes": [], "start": "a"}])
def test_malformed_input_is_reported_not_raised(definition):
    assert validate(definition) != []


def test_a_notify_step_does_not_count_as_an_approval():
    workflow = {
        "subject": "request", "start": "tell",
        "nodes": [{"id": "tell", "kind": "notify", "to_role": "finance", "message": "New request", "next": "end"}],
    }

    assert any("no approval" in problem for problem in validate(workflow))
