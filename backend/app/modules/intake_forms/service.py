"""Request types and their forms: admins build them, requesters answer them (BUILD_PLAN §5, change 40).

A request type ("Software purchase", "New laptop") adds its own questions to the purchase
request form. The answers are stored on the request and are available to the workflow engine as
`custom.<key>`, so an admin can route on them. A form can add questions; it cannot remove a
control: the request still goes through the same approvals and segregation of duties (§9).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import FormField, RequestType, User
from app.modules.audit.service import record_event
from app.modules.intake_forms.fields import KEY_FORMAT, clean_values, field_problems

EDITOR_ROLES = ("admin",)


def fields_of(db: Session, request_type: RequestType) -> list[dict[str, Any]]:
    rows = db.scalars(select(FormField).where(FormField.request_type_id == request_type.id)
                      .order_by(FormField.position))
    return [{"key": f.key, "label": f.label, "kind": f.kind, "required": f.required, "options": list(f.options or [])}
            for f in rows]


def as_dict(db: Session, request_type: RequestType) -> dict[str, Any]:
    return {"id": request_type.id, "key": request_type.key, "name": request_type.name,
            "description": request_type.description, "active": request_type.active,
            "fields": fields_of(db, request_type)}


def list_types(db: Session, user: User) -> list[RequestType]:
    """Everyone sees the types in use; an admin also sees the ones switched off."""
    query = select(RequestType).where(RequestType.org_id == user.org_id).order_by(RequestType.name)
    if user.role not in EDITOR_ROLES:
        query = query.where(RequestType.active)
    return list(db.scalars(query))


def load_type(db: Session, org_id: uuid.UUID, type_id: uuid.UUID, *, lock: bool = False) -> RequestType:
    query = select(RequestType).where(RequestType.id == type_id, RequestType.org_id == org_id)
    request_type = db.scalar(query.with_for_update() if lock else query)
    if request_type is None:
        raise NotFound("Request type not found.")
    return request_type


def save_type(db: Session, user: User, *, type_id: uuid.UUID | None, key: str, name: str, description: str,
              active: bool, fields: list[dict[str, Any]]) -> RequestType:
    """Create a type, or replace an existing type's name and questions. Its key never changes."""
    if user.role not in EDITOR_ROLES:
        raise Forbidden("Only an admin can change request types.")
    problems = field_problems(fields)
    if problems:
        raise Invalid(" ".join(problems))
    name = name.strip()
    if not name:
        raise Invalid("Give the request type a name.")
    if type_id is None:
        if not KEY_FORMAT.match(key):
            raise Invalid("The key must be lower-case letters, digits or _ and start with a letter.")
        if db.scalar(select(RequestType.id).where(RequestType.org_id == user.org_id, RequestType.key == key)):
            raise Conflict("A request type with this key already exists.")
        request_type = RequestType(id=uuid.uuid4(), org_id=user.org_id, key=key, name=name,
                                   description=description.strip(), active=active)
        db.add(request_type)
        action = "created"
    else:
        request_type = load_type(db, user.org_id, type_id, lock=True)
        request_type.name, request_type.description, request_type.active = name, description.strip(), active
        for old in db.scalars(select(FormField).where(FormField.request_type_id == request_type.id)):
            db.delete(old)
        action = "updated"
    db.flush()
    for position, field in enumerate(fields):
        db.add(FormField(org_id=user.org_id, request_type_id=request_type.id, key=field["key"],
                         label=field["label"].strip(), kind=field["kind"], required=bool(field.get("required")),
                         options=[o.strip() for o in field.get("options") or []], position=position))
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="request_type", entity_id=request_type.id, actor_id=user.id,
                 action=action, payload={"key": request_type.key, "name": name, "active": active,
                                         "fields": [f"{f['key']}:{f['kind']}" for f in fields]})
    return request_type


def checked_answers(db: Session, org_id: uuid.UUID, type_id: uuid.UUID,
                    values: dict[str, Any]) -> tuple[RequestType, dict[str, str]]:
    """The answers to store on a request of this type, or a refusal naming every problem."""
    request_type = db.scalar(select(RequestType).where(RequestType.id == type_id, RequestType.org_id == org_id,
                                                       RequestType.active))
    if request_type is None:
        raise Invalid("Choose a request type from the list.")
    fields = fields_of(db, request_type)
    clean, problems = clean_values(fields, values)
    people = [uuid.UUID(clean[f["key"]]) for f in fields if f["kind"] == "user" and f["key"] in clean]
    if people:
        # A person picked on a form must work for this org; another org's user id is not accepted.
        found = set(db.scalars(select(User.id).where(User.org_id == org_id, User.active, User.id.in_(people))))
        if found != set(people):
            problems.append("Choose people from the list.")
    if problems:
        raise Invalid(" ".join(problems))
    return request_type, clean
