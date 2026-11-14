"""App Studio (BUILD_PLAN change 49): a custom object is a form, one approval step and a list view.

An admin defines the questions (the same field kinds and checks as intake forms) and which role
approves. People then create records; someone with that role, but never the record's creator,
approves or rejects them with an audit trail. Nothing here runs customer code: a definition is data,
answers are text checked against it, and the list view only shows stored values.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import AppObject, AppRecord, User
from app.modules.audit.service import record_event
from app.modules.intake_forms.fields import clean_values, field_problems

APPROVER_ROLES = ("approver", "finance", "admin")
KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def as_dict(obj: AppObject) -> dict[str, Any]:
    return {"id": obj.id, "key": obj.key, "name": obj.name, "fields": obj.fields, "approver_role": obj.approver_role,
            "list_columns": obj.list_columns, "active": obj.active}


def save_object(db: Session, user: User, *, key: str, name: str, fields: list[dict[str, Any]], approver_role: str,
                list_columns: list[str]) -> AppObject:
    if user.role != "admin":
        raise Forbidden("Only an admin can build apps.")
    problems = field_problems(fields)
    if not KEY.match(key):
        problems.append("The key must be lower-case letters, digits or _ and start with a letter.")
    if approver_role not in APPROVER_ROLES:
        problems.append(f"The approver must be one of: {', '.join(APPROVER_ROLES)}.")
    unknown = set(list_columns) - {f["key"] for f in fields}
    if unknown or not list_columns:
        problems.append("List columns must be keys of the questions on the form.")
    if problems or not name.strip():
        raise Invalid(" ".join(problems) or "Give the app a name.")
    clean = [{"key": f["key"], "label": f["label"].strip(), "kind": f["kind"], "required": bool(f.get("required")),
              "options": [o.strip() for o in f.get("options") or []]} for f in fields]
    obj = db.scalar(select(AppObject).where(AppObject.org_id == user.org_id, AppObject.key == key).with_for_update())
    if obj is None:
        obj = AppObject(id=uuid.uuid4(), org_id=user.org_id, key=key, name=name.strip()[:120], fields=clean,
                        approver_role=approver_role, list_columns=list_columns, created_by=user.id)
        db.add(obj)
    elif db.scalar(select(AppRecord.id).where(AppRecord.object_id == obj.id).limit(1)) is not None:
        raise Conflict("This app already has records; create a new app instead of changing its questions.")
    else:
        obj.name, obj.fields, obj.approver_role, obj.list_columns = name.strip()[:120], clean, approver_role, list_columns
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="app_object", entity_id=obj.id, actor_id=user.id, action="saved",
                 payload={"key": key, "fields": [f"{f['key']}:{f['kind']}" for f in clean], "approver_role": approver_role})
    return obj


def list_objects(db: Session, user: User) -> list[AppObject]:
    return list(db.scalars(select(AppObject).where(AppObject.org_id == user.org_id, AppObject.active)
                           .order_by(AppObject.name)))


def load_object(db: Session, user: User, object_id: uuid.UUID) -> AppObject:
    obj = db.scalar(select(AppObject).where(AppObject.id == object_id, AppObject.org_id == user.org_id))
    if obj is None:
        raise NotFound("App not found.")
    return obj


def create_record(db: Session, user: User, object_id: uuid.UUID, values: dict[str, Any]) -> AppRecord:
    obj = load_object(db, user, object_id)
    clean, problems = clean_values(obj.fields, values)
    people = [clean[f["key"]] for f in obj.fields if f["kind"] == "user" and f["key"] in clean]
    if people and len(set(db.scalars(select(User.id).where(User.org_id == user.org_id,
                                                           User.id.in_([uuid.UUID(p) for p in people]))))) != len(set(people)):
        problems.append("Choose people from the list.")
    if problems:
        raise Invalid(" ".join(problems))
    record = AppRecord(id=uuid.uuid4(), org_id=user.org_id, object_id=obj.id, values=clean, status="submitted",
                       created_by=user.id)
    db.add(record)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="app_record", entity_id=record.id, actor_id=user.id,
                 action="submitted", payload={"app": obj.key})
    return record


def decide(db: Session, user: User, object_id: uuid.UUID, record_id: uuid.UUID, decision: str, reason: str | None) -> AppRecord:
    obj = load_object(db, user, object_id)
    record = db.scalar(select(AppRecord).where(AppRecord.id == record_id, AppRecord.object_id == obj.id).with_for_update())
    if record is None:
        raise NotFound("Record not found.")
    if decision not in ("approve", "reject"):
        raise Invalid("Decision must be approve or reject.")
    if user.role != obj.approver_role and user.role != "admin":
        raise Forbidden(f"Only {obj.approver_role} can decide these records.")
    if record.created_by == user.id:
        raise Forbidden("You created this record, so someone else must decide it.")
    if record.status != "submitted":
        raise Conflict("This record was already decided.")
    if decision == "reject" and not (reason or "").strip():
        raise Invalid("Give a reason when you reject.")
    record.status = "approved" if decision == "approve" else "rejected"
    record.decided_by, record.decided_at, record.reason = user.id, datetime.now(UTC), (reason or "").strip() or None
    record_event(db, org_id=user.org_id, entity_type="app_record", entity_id=record.id, actor_id=user.id,
                 action=record.status, payload={"app": obj.key, "reason": record.reason})
    return record


def list_view(db: Session, user: User, object_id: uuid.UUID) -> dict[str, Any]:
    obj = load_object(db, user, object_id)
    query = select(AppRecord).where(AppRecord.object_id == obj.id).order_by(AppRecord.created_at.desc())
    if user.role not in APPROVER_ROLES:
        query = query.where(AppRecord.created_by == user.id)  # a requester sees their own records only
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    labels = {f["key"]: f["label"] for f in obj.fields}
    return {"app": as_dict(obj), "columns": [{"key": c, "label": labels[c]} for c in obj.list_columns],
            "records": [{"id": r.id, "status": r.status, "values": r.values, "created_by": names.get(r.created_by),
                         "decided_by": names.get(r.decided_by), "reason": r.reason, "created_at": r.created_at,
                         "can_decide": r.status == "submitted" and r.created_by != user.id
                         and user.role in (obj.approver_role, "admin")}
                        for r in db.scalars(query.limit(200))]}
