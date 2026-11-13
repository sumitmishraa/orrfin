"""Saving, simulating and publishing workflow versions (ADR 0010, BUILD_PLAN §9 v3.0).

Rules enforced here:
- only an admin saves or publishes;
- a version can be published only if `definition.validate` finds no problem and every named
  approver is an active user of the same org;
- a published version is never edited. Publishing writes a new row and retires the old one;
- if the new version would ask for *fewer* approvals than the version in use for any request
  it can tell apart, the admin who saved it cannot publish it: a second admin must (§9);
- every save and publish is audited with the version's SHA-256, in the same transaction.

Nothing here approves anything. The published definition only tells procurement which steps a
request needs; who may decide each step stays in procurement.decision_refusal.
"""

import hashlib
import itertools
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import ApprovalPolicy, User, WorkflowDefinition, WorkflowVersion
from app.modules.audit.service import record_event
from app.modules.workflow_engine.definition import FIELDS, field_type, parse_money, validate
from app.modules.workflow_engine.evaluate import approval_steps, route

EDITOR_ROLES = ("admin",)
# The one workflow procurement looks for when a request is sent for approval.
REQUEST_APPROVAL_KEY = "request-approval"
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")
ONE_PAISA = Decimal("0.01")
# How many sample requests the "fewer approvals?" check may compare. Above this the check
# cannot be exhaustive, so it treats the change as lowering (fail closed).
MAX_PROBES = 5000
OTHER_VALUE = "(anything else)"


def definition_hash(definition: dict[str, Any]) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_editor(user: User) -> None:
    if user.role not in EDITOR_ROLES:
        raise Forbidden("Only an admin can change workflows.")


# --- Checks that need the database -----------------------------------------------------------

def problems_for(db: Session, org_id: uuid.UUID, definition: Any) -> list[str]:
    """`validate` plus: every named approver must be an active user of this org."""
    problems = validate(definition)
    if problems:
        return problems
    for node in definition["nodes"]:
        approver_id = node.get("approver_id") if node["kind"] == "approval" else None
        if approver_id is None:
            continue
        found = db.scalar(select(User.id).where(User.id == uuid.UUID(str(approver_id)),
                                                User.org_id == org_id, User.active))
        if found is None:
            problems.append(f'Step "{node["id"]}": the named person is not an active user of this company.')
    return problems


# --- "Does this version ask for fewer approvals?" --------------------------------------------

def _leaf_rules(rule: dict[str, Any]) -> list[dict[str, Any]]:
    for joiner in ("all", "any"):
        if joiner in rule:
            return [leaf for part in rule[joiner] for leaf in _leaf_rules(part)]
    return [rule]


def _probe_facts(definitions: list[dict[str, Any]], boundary_amounts: set[Decimal]) -> list[dict[str, Any]] | None:
    """Sample requests that land on every side of every condition in these definitions.

    For each amount a condition mentions, and each of `boundary_amounts` (the built-in tier
    limits, when those are what is being replaced): that amount and one paisa either side. For
    each text value: that value, plus one value no condition mentions. Returns None when there
    would be too many combinations to compare them all.
    """
    values: dict[str, set[Any]] = {"amount": {ONE_PAISA}}
    for amount in boundary_amounts:
        values["amount"].update({amount, amount + ONE_PAISA} | ({amount - ONE_PAISA} if amount > ONE_PAISA else set()))
    for definition in definitions:
        subject = definition["subject"]
        for node in definition["nodes"]:
            if node["kind"] != "condition":
                continue
            for rule in _leaf_rules(node["when"]):
                field = rule["field"]
                bucket = values.setdefault(field, set())
                if field_type(subject, field) == "money":
                    amount = parse_money(rule["value"])
                    bucket.update({amount - ONE_PAISA, amount, amount + ONE_PAISA})
                else:
                    options = rule["value"] if isinstance(rule["value"], list) else [rule["value"]]
                    bucket.update(options)
                    bucket.add(OTHER_VALUE)

    fields = sorted(values)
    total = 1
    for field in fields:
        total *= len(values[field])
        if total > MAX_PROBES:
            return None
    return [dict(zip(fields, combination, strict=True))
            for combination in itertools.product(*(sorted(values[f], key=str) for f in fields))]


def _tier_step_count(db: Session, org_id: uuid.UUID, amount: Decimal) -> int:
    """Approval steps the built-in amount tiers (§9) ask for; what applies before any workflow is published."""
    policy = db.scalar(select(ApprovalPolicy).where(
        ApprovalPolicy.org_id == org_id, ApprovalPolicy.active, ApprovalPolicy.min_amount <= amount,
        (ApprovalPolicy.max_amount.is_(None)) | (ApprovalPolicy.max_amount >= amount),
    ).order_by(ApprovalPolicy.min_amount.desc()).limit(1))
    return len(policy.steps) if policy else 0


def fewer_approval_cases(db: Session, org_id: uuid.UUID, current: dict[str, Any] | None,
                         proposed: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Sample requests for which `proposed` needs fewer approvals than what is in use now.

    `current` is the published definition, or None when the built-in amount tiers still apply.
    Returns [] when nothing is lowered, and None when it could not compare every case.
    """
    tier_limits: set[Decimal] = set()
    if current is None:
        # Replacing the built-in tiers: a workflow with no conditions of its own must still be
        # compared at every tier limit, or "manager only" would look no weaker than the tiers.
        for low, high in db.execute(select(ApprovalPolicy.min_amount, ApprovalPolicy.max_amount).where(
                ApprovalPolicy.org_id == org_id, ApprovalPolicy.active)).all():
            tier_limits.update(limit for limit in (low, high) if limit is not None and limit > 0)
    probes = _probe_facts([proposed] if current is None else [current, proposed], tier_limits)
    if probes is None:
        return None
    lowered = []
    for facts in probes:
        before = (len(approval_steps(current, facts)) if current is not None
                  else _tier_step_count(db, org_id, facts.get("amount", ONE_PAISA)))
        after = len(approval_steps(proposed, facts))
        if after < before:
            lowered.append({"facts": facts, "approvals_now": before, "approvals_proposed": after})
    return lowered


# --- Reading ---------------------------------------------------------------------------------

def active_version(db: Session, org_id: uuid.UUID, key: str) -> WorkflowVersion | None:
    """The published version of this workflow for the org, or None if it has never been published."""
    return db.scalar(
        select(WorkflowVersion)
        .join(WorkflowDefinition, WorkflowDefinition.active_version_id == WorkflowVersion.id)
        .where(WorkflowDefinition.org_id == org_id, WorkflowDefinition.key == key,
               WorkflowVersion.status == "published"))


def _version_summary(version: WorkflowVersion) -> dict[str, Any]:
    return {"id": version.id, "number": version.number, "status": version.status, "sha256": version.sha256,
            "drafted_by_ai": version.drafted_by_ai, "created_by": version.created_by,
            "published_by": version.published_by, "published_at": version.published_at,
            "created_at": version.created_at}


def list_definitions(db: Session, user: User) -> list[dict[str, Any]]:
    definitions = db.scalars(select(WorkflowDefinition).where(WorkflowDefinition.org_id == user.org_id)
                             .order_by(WorkflowDefinition.name)).all()
    return [{"id": d.id, "key": d.key, "name": d.name, "subject_type": d.subject_type,
             "active_version_id": d.active_version_id} for d in definitions]


def get_definition(db: Session, user: User, definition_id: uuid.UUID) -> dict[str, Any]:
    definition = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == definition_id, WorkflowDefinition.org_id == user.org_id))
    if definition is None:
        raise NotFound("Workflow not found.")
    versions = db.scalars(select(WorkflowVersion).where(WorkflowVersion.definition_id == definition.id)
                          .order_by(WorkflowVersion.number.desc())).all()
    return {"id": definition.id, "key": definition.key, "name": definition.name,
            "subject_type": definition.subject_type, "active_version_id": definition.active_version_id,
            "versions": [{**_version_summary(v), "definition": v.definition} for v in versions]}


def simulate(db: Session, user: User, definition: Any, facts: dict[str, Any]) -> dict[str, Any]:
    """What this definition would do for these sample facts. Changes nothing."""
    problems = problems_for(db, user.org_id, definition)
    if problems:
        return {"problems": problems, "route": [], "approvals": []}
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    approvals = [{**step, "approver_name": names.get(step["approver_id"])}
                 for step in approval_steps(definition, facts)]
    return {"problems": [], "route": route(definition, facts), "approvals": approvals}


# --- Writing ---------------------------------------------------------------------------------

def save_draft(db: Session, user: User, *, key: str, name: str, definition: Any,
               drafted_by_ai: bool = False) -> WorkflowVersion:
    """Save a new draft version (creating the workflow on first save). A draft may still have
    problems; they are returned by the router and block publishing, not saving."""
    _require_editor(user)
    if not KEY_PATTERN.fullmatch(key):
        raise Invalid("The workflow key must be 3 to 60 lowercase letters, digits or hyphens.")
    name = name.strip()
    if not name:
        raise Invalid("Give the workflow a name.")
    if not isinstance(definition, dict) or definition.get("subject") not in FIELDS:
        raise Invalid(f"A workflow must say which record it runs on: {', '.join(FIELDS)}.")

    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.org_id == user.org_id, WorkflowDefinition.key == key).with_for_update())
    if workflow is None:
        workflow = WorkflowDefinition(id=uuid.uuid4(), org_id=user.org_id, key=key, name=name,
                                      subject_type=definition["subject"])
        db.add(workflow)
        db.flush()
    elif workflow.subject_type != definition["subject"]:
        raise Invalid(f"This workflow runs on {workflow.subject_type} records; that cannot be changed.")
    else:
        workflow.name = name

    number = (db.scalar(select(func.max(WorkflowVersion.number))
                        .where(WorkflowVersion.definition_id == workflow.id)) or 0) + 1
    version = WorkflowVersion(id=uuid.uuid4(), org_id=user.org_id, definition_id=workflow.id, number=number,
                              definition=definition, sha256=definition_hash(definition), status="draft",
                              drafted_by_ai=drafted_by_ai, created_by=user.id)
    db.add(version)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="workflow_definition", entity_id=workflow.id,
                 actor_id=user.id, action="draft_saved",
                 payload={"version": number, "sha256": version.sha256, "drafted_by_ai": drafted_by_ai})
    return version


def publish(db: Session, user: User, version_id: uuid.UUID) -> WorkflowVersion:
    _require_editor(user)
    version = db.scalar(select(WorkflowVersion).where(
        WorkflowVersion.id == version_id, WorkflowVersion.org_id == user.org_id))
    if version is None:
        raise NotFound("Workflow version not found.")
    # Lock the workflow row: two admins publishing at once must not both become "the active version".
    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == version.definition_id).with_for_update())
    db.refresh(version)
    if version.status != "draft":
        raise Conflict("Only a draft can be published. To change a published workflow, save a new version.")
    if version.sha256 != definition_hash(version.definition):
        # Defence in depth: the stored steps no longer match the hash taken when they were saved.
        raise Conflict("This draft was changed outside the app and cannot be published. Save it again.")

    problems = problems_for(db, user.org_id, version.definition)
    if problems:
        raise Invalid("This workflow cannot be published yet: " + " ".join(problems))

    current = db.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
    lowered = fewer_approval_cases(db, user.org_id, current.definition if current else None, version.definition)
    lowers_requirement = lowered is None or bool(lowered)
    if lowers_requirement and version.created_by == user.id:
        raise Forbidden("This version needs fewer approvals than what is in use for some requests. "
                        "A second admin must publish it.")

    if current is not None:
        current.status = "retired"
    version.status, version.published_by, version.published_at = "published", user.id, datetime.now(UTC)
    workflow.active_version_id = version.id
    record_event(db, org_id=user.org_id, entity_type="workflow_definition", entity_id=workflow.id,
                 actor_id=user.id, action="published",
                 payload={"version": version.number, "sha256": version.sha256,
                          "replaces_version": current.number if current else None,
                          "drafted_by": version.created_by, "drafted_by_ai": version.drafted_by_ai,
                          "lowers_requirement": lowers_requirement,
                          "lowered_examples": (lowered or [])[:5]})
    return version
