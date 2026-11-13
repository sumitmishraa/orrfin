"""The shape of a workflow definition and the checks it must pass before it can be published (ADR 0010).

A definition is plain JSON, written by an admin in the builder or drafted by the AI agent:

    {"subject": "request",
     "start": "big",
     "nodes": [
       {"id": "big", "kind": "condition",
        "when": {"field": "amount", "op": ">", "value": "500000.00"}, "then": "cfo", "else": "mgr"},
       {"id": "mgr", "kind": "approval", "role": "manager", "next": "end"},
       {"id": "cfo", "kind": "approval", "role": "finance", "label": "CFO sign-off", "next": "end"}]}

`validate` returns a list of plain-English problems; an empty list means the definition is safe
to publish. It is deliberately strict, because a published workflow decides who must approve money:
- no loops, no step that can never be reached, no route that never ends;
- every route passes through at least one approval, so no request can approve itself;
- conditions may only compare known fields with a fixed set of operators. There is no code to
  run, so a definition (including one drafted by an AI) cannot do anything except choose steps.
"""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

# The reserved name for "the workflow is finished".
END = "end"
NODE_KINDS = ("condition", "approval", "notify")
OPERATORS = ("==", "!=", ">", ">=", "<", "<=", "in")
ORDERING_OPERATORS = (">", ">=", "<", "<=")
# Who a role-based approval step may name. "manager" means the requester's own manager (§9).
# Requesters and buyers are left out on purpose: they prepare a request, they never approve it.
APPROVAL_ROLES = ("manager", "approver", "finance", "admin")
NOTIFY_ROLES = ("requester", "buyer", "approver", "finance", "admin")

# The facts a condition may look at, per kind of record, and how each is compared.
FIELDS: dict[str, dict[str, str]] = {
    "request": {
        "amount": "money",
        "currency": "text",
        "category": "text",
        "cost_center": "text",
        "request_type": "text",
    },
}
# Answers to an intake form's extra questions (intake_forms) are addressed as "custom.<key>".
CUSTOM_PREFIX = "custom."

# Limits that keep a definition readable by a person and cheap to check.
MAX_NODES = 50
MAX_CONDITION_DEPTH = 3
MAX_LABEL_LENGTH = 80
MAX_MESSAGE_LENGTH = 300


def field_type(subject: str, field: str) -> str | None:
    """How a field is compared ("money" or "text"), or None if conditions may not use it."""
    if field.startswith(CUSTOM_PREFIX) and len(field) > len(CUSTOM_PREFIX):
        return "text"
    return FIELDS.get(subject, {}).get(field)


def parse_money(value: Any) -> Decimal | None:
    """An exact amount from a definition, or None. Floats are refused: 0.1 is not exact (§5 money rule)."""
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, (int, str)):
        try:
            amount = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return amount if amount.is_finite() else None
    return None


def _condition_problems(subject: str, condition: Any, where: str, depth: int = 1) -> list[str]:
    if not isinstance(condition, dict):
        return [f"{where}: the condition must be a rule such as amount > 50000."]
    if depth > MAX_CONDITION_DEPTH:
        return [f"{where}: the condition is nested too deeply. Split it into two condition steps."]

    for joiner in ("all", "any"):
        if joiner in condition:
            parts = condition[joiner]
            if set(condition) != {joiner} or not isinstance(parts, list) or not parts:
                return [f'{where}: "{joiner}" must hold a list of at least one rule and nothing else.']
            problems: list[str] = []
            for part in parts:
                problems += _condition_problems(subject, part, where, depth + 1)
            return problems

    field, operator, value = condition.get("field"), condition.get("op"), condition.get("value")
    if set(condition) != {"field", "op", "value"} or not isinstance(field, str):
        return [f'{where}: a rule needs exactly "field", "op" and "value".']
    kind = field_type(subject, field)
    if kind is None:
        known = ", ".join(sorted(FIELDS[subject])) + ", custom.<form field>"
        return [f'{where}: "{field}" is not a field a condition can use. Use one of: {known}.']
    if operator not in OPERATORS:
        return [f'{where}: "{operator}" is not a comparison. Use one of: {", ".join(OPERATORS)}.']

    if operator == "in":
        if kind != "text" or not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            return [f'{where}: "in" needs a list of text values, for example ["IT hardware", "Software"].']
        return []
    if kind == "money":
        if parse_money(value) is None:
            return [f'{where}: write the amount as a number in quotes, for example "50000.00".']
        return []
    if operator in ORDERING_OPERATORS:
        return [f'{where}: "{field}" is text, so it can only be compared with ==, != or in.']
    if not isinstance(value, str):
        return [f'{where}: "{field}" must be compared with a text value in quotes.']
    return []


def _node_problems(subject: str, node: dict[str, Any], targets: set[str]) -> list[str]:
    """Problems inside one step. `targets` are the names a step may point to next."""
    node_id, kind = node["id"], node["kind"]
    where = f'Step "{node_id}"'
    problems: list[str] = []

    def check_target(key: str) -> None:
        target = node.get(key)
        if target not in targets:
            problems.append(f'{where}: "{key}" must name another step or "{END}"; "{target}" does not exist.')

    if kind == "condition":
        problems += _condition_problems(subject, node.get("when"), where)
        check_target("then")
        check_target("else")
    elif kind == "approval":
        role, approver_id = node.get("role"), node.get("approver_id")
        if (role is None) == (approver_id is None):
            problems.append(f"{where}: an approval needs either a role or one named person, not both.")
        elif role is not None and role not in APPROVAL_ROLES:
            problems.append(f'{where}: "{role}" cannot approve. Use one of: {", ".join(APPROVAL_ROLES)}.')
        elif approver_id is not None:
            try:
                uuid.UUID(str(approver_id))
            except ValueError:
                problems.append(f"{where}: the named person is not a valid user.")
        label = node.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_LENGTH):
            problems.append(f"{where}: the label must be 1 to {MAX_LABEL_LENGTH} characters.")
        check_target("next")
    else:  # notify
        if node.get("to_role") not in NOTIFY_ROLES:
            problems.append(f'{where}: choose who to notify: {", ".join(NOTIFY_ROLES)}.')
        message = node.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_LENGTH:
            problems.append(f"{where}: the message must be 1 to {MAX_MESSAGE_LENGTH} characters.")
        check_target("next")
    return problems


def next_steps(node: dict[str, Any]) -> list[str]:
    """Where a step can lead: both branches of a condition, or the single next step."""
    return [node["then"], node["else"]] if node["kind"] == "condition" else [node["next"]]


def _graph_problems(start: str, by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Loops, unreachable steps, and routes that would finish with nobody approving."""
    visiting: set[str] = set()
    finished: set[str] = set()
    loop_at: list[str] = []

    def walk(node_id: str) -> None:
        if node_id == END or node_id in finished or loop_at:
            return
        if node_id in visiting:
            loop_at.append(node_id)
            return
        visiting.add(node_id)
        for target in next_steps(by_id[node_id]):
            walk(target)
        visiting.discard(node_id)
        finished.add(node_id)

    walk(start)
    if loop_at:
        return [f'Step "{loop_at[0]}" leads back to itself. A workflow cannot loop.']

    problems = [f'Step "{node_id}" can never be reached.' for node_id in by_id if node_id not in finished]

    ends_unapproved: dict[str, bool] = {}

    def can_end_without_approval(node_id: str) -> bool:
        if node_id == END:
            return True
        if node_id not in ends_unapproved:
            node = by_id[node_id]
            ends_unapproved[node_id] = node["kind"] != "approval" and any(
                can_end_without_approval(target) for target in next_steps(node))
        return ends_unapproved[node_id]

    if can_end_without_approval(start):
        problems.append("Some route through this workflow ends with no approval. "
                        "Every route needs at least one approval step.")
    return problems


def validate(definition: Any) -> list[str]:
    """Every reason this definition cannot be published, in plain English. Empty list = publishable."""
    if not isinstance(definition, dict):
        return ["A workflow must be an object with a subject, a start and a list of steps."]
    subject = definition.get("subject")
    if subject not in FIELDS:
        return [f'"{subject}" is not a kind of record a workflow can run on. Use one of: {", ".join(FIELDS)}.']
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["Add at least one step."]
    if len(nodes) > MAX_NODES:
        return [f"A workflow can have at most {MAX_NODES} steps."]

    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id") if isinstance(node, dict) else None
        if not isinstance(node_id, str) or not node_id.strip() or node_id == END:
            return [f'Every step needs a name of its own, and "{END}" is reserved.']
        if node_id in by_id:
            return [f'Two steps are both named "{node_id}".']
        if node.get("kind") not in NODE_KINDS:
            return [f'Step "{node_id}": the kind must be one of: {", ".join(NODE_KINDS)}.']
        by_id[node_id] = node

    start = definition.get("start")
    if start not in by_id:
        return ["Choose which step the workflow starts with."]

    targets = set(by_id) | {END}
    problems: list[str] = []
    for node in nodes:
        problems += _node_problems(subject, node, targets)
    # The route checks follow the arrows, so they only make sense once every arrow points somewhere real.
    return problems or _graph_problems(start, by_id)
