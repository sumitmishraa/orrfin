"""The questions on an intake form and the answers given to them (BUILD_PLAN §5 `form_fields`). Pure.

A form is a list of fields; an answer set is a dict of field key → text. Answers are always
text on the way in (a money answer is a decimal string, never a JSON number), are checked
against the form, and are stored exactly as cleaned here. Nothing in an answer is ever run:
a form is data, not code.
"""

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

FIELD_KINDS = ("text", "number", "money", "date", "choice", "user")
KEY_FORMAT = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_FIELDS = 40
MAX_OPTIONS = 50
MAX_TEXT = 2000
DECIMAL_TEXT = re.compile(r"^-?\d{1,15}(\.\d{1,6})?$")
MONEY_TEXT = re.compile(r"^\d{1,15}(\.\d{1,2})?$")


def field_problems(fields: list[dict[str, Any]]) -> list[str]:
    """Why this list of fields cannot be saved, in words an admin can act on. Empty when it can."""
    problems: list[str] = []
    if len(fields) > MAX_FIELDS:
        problems.append(f"A form can have at most {MAX_FIELDS} questions.")
    seen: set[str] = set()
    for number, field in enumerate(fields, start=1):
        key, label, kind = field.get("key") or "", (field.get("label") or "").strip(), field.get("kind")
        where = f"Question {number}"
        if not KEY_FORMAT.match(key):
            problems.append(f"{where}: the key must be lower-case letters, digits or _ and start with a letter.")
        elif key in seen:
            problems.append(f'{where}: the key "{key}" is used twice.')
        seen.add(key)
        if not label or len(label) > 120:
            problems.append(f"{where}: give the question a label of up to 120 characters.")
        if kind not in FIELD_KINDS:
            problems.append(f"{where}: the kind must be one of {', '.join(FIELD_KINDS)}.")
        options = field.get("options") or []
        if kind == "choice":
            texts = [o.strip() for o in options if isinstance(o, str) and o.strip()]
            if len(texts) != len(options) or not 1 <= len(texts) <= MAX_OPTIONS or len(set(texts)) != len(texts):
                problems.append(f"{where}: a choice needs 1 to {MAX_OPTIONS} different options.")
            elif any(len(o) > 120 for o in texts):
                problems.append(f"{where}: an option can have at most 120 characters.")
        elif options:
            problems.append(f"{where}: only a choice question has options.")
    return problems


def _clean_one(field: dict[str, Any], raw: str) -> tuple[str | None, str | None]:
    """One answer → (the value to store, None) or (None, why it is refused)."""
    kind, label = field["kind"], field["label"]
    if kind == "text":
        return (raw, None) if len(raw) <= MAX_TEXT else (None, f"{label}: at most {MAX_TEXT} characters.")
    if kind == "number":
        return (raw, None) if DECIMAL_TEXT.match(raw) else (None, f"{label}: enter a plain number.")
    if kind == "money":
        if not MONEY_TEXT.match(raw):
            return None, f"{label}: enter an amount such as 54870.00 (no commas or symbols)."
        try:
            return f"{Decimal(raw):.2f}", None
        except InvalidOperation:
            return None, f"{label}: enter an amount such as 54870.00."
    if kind == "date":
        try:
            return date.fromisoformat(raw).isoformat(), None
        except ValueError:
            return None, f"{label}: use a real date in the form YYYY-MM-DD."
    if kind == "choice":
        return (raw, None) if raw in field["options"] else (None, f"{label}: choose one of the listed options.")
    try:  # kind == "user": the service checks the person belongs to this org
        return str(uuid.UUID(raw)), None
    except ValueError:
        return None, f"{label}: choose a person from the list."


def clean_values(fields: list[dict[str, Any]], values: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Check a set of answers against a form. Returns (answers to store, problems)."""
    clean: dict[str, str] = {}
    problems = [f'"{key}" is not a question on this form.' for key in values if key not in {f["key"] for f in fields}]
    for field in fields:
        raw = values.get(field["key"])
        if raw is not None and not isinstance(raw, str):
            # A JSON number could have been a float; every answer travels as text.
            problems.append(f"{field['label']}: send the answer as text.")
            continue
        raw = (raw or "").strip()
        if not raw:
            if field["required"]:
                problems.append(f"{field['label']}: this question must be answered.")
            continue
        value, problem = _clean_one(field, raw)
        if problem:
            problems.append(problem)
        else:
            clean[field["key"]] = value
    return clean, problems
