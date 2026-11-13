"""Walk a validated workflow definition for one record's facts (ADR 0010).

Pure and deterministic: `route(definition, facts)` returns the steps the record passes through,
in order. It is used three ways, always giving the same answer for the same input:
- when a request is sent for approval, to build its approval chain;
- by "Simulate" in the builder, on sample facts, before an admin publishes;
- by the chain preview on the request form.

Comparison rules, chosen so a missing or odd value can never *skip* an approval by accident:
- money is compared exactly, as Decimal;
- text is compared without regard to case or surrounding spaces;
- a fact the record does not have makes its rule false (so "amount > X" is false, not an error).
"""

import uuid
from decimal import Decimal
from typing import Any

from app.modules.workflow_engine.definition import END, field_type, next_steps, parse_money

# How a workflow's "one named person" step is stored on the approval chain. It reuses the
# value procurement already understands (the category reviewer step of §9): only the named
# person may decide it, and no spending limit applies because it reviews fitness, not money.
NAMED_REVIEWER_STEP = "category_reviewer"


def _text(value: Any) -> str:
    return str(value).strip().casefold()


def _rule_holds(subject: str, rule: dict[str, Any], facts: dict[str, Any]) -> bool:
    if "all" in rule:
        return all(_rule_holds(subject, part, facts) for part in rule["all"])
    if "any" in rule:
        return any(_rule_holds(subject, part, facts) for part in rule["any"])

    field, operator, expected = rule["field"], rule["op"], rule["value"]
    actual = facts.get(field)
    if actual is None:
        return False

    if operator == "in":
        return _text(actual) in {_text(option) for option in expected}

    if field_type(subject, field) == "money":
        left, right = parse_money(actual if not isinstance(actual, Decimal) else str(actual)), parse_money(expected)
        if left is None or right is None:
            return False
    else:
        left, right = _text(actual), _text(expected)

    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    return left <= right


def route(definition: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps this record passes through, in order. Each condition step also says which way it went."""
    by_id = {node["id"]: node for node in definition["nodes"]}
    subject = definition["subject"]
    visited: list[dict[str, Any]] = []
    current = definition["start"]
    # validate() already forbids loops; the bound makes a definition that somehow skipped
    # validation stop instead of spinning.
    for _ in range(len(by_id) + 1):
        if current == END:
            return visited
        node = by_id[current]
        if node["kind"] == "condition":
            holds = _rule_holds(subject, node["when"], facts)
            visited.append({**node, "result": holds})
            current = node["then"] if holds else node["else"]
        else:
            visited.append(dict(node))
            current = next_steps(node)[0]
    raise ValueError("Workflow definition loops; it must be validated before it is run.")


def approval_steps(definition: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The approval chain for these facts, in the shape procurement.chain_preview returns."""
    steps: list[dict[str, Any]] = []
    for node in route(definition, facts):
        if node["kind"] != "approval":
            continue
        if node.get("approver_id") is not None:
            steps.append({"role": NAMED_REVIEWER_STEP, "label": node.get("label") or "Named review",
                          "approver_id": uuid.UUID(str(node["approver_id"]))})
        else:
            steps.append({"role": node["role"], "label": node.get("label"), "approver_id": None})
    return steps
