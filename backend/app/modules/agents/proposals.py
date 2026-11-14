"""Proposals: what an AI suggested, which only a person can turn into a real record (BUILD_PLAN change 47).

A proposal is stored with the SHA-256 of its payload, belongs to the person whose chat made it,
expires after 30 minutes and works once. Submitting it calls the very same service function as the
normal page (create a draft request, invite a supplier, save a workflow draft, create a draft RFQ),
which repeats every permission and rule check. So a proposal can never do more than its person could
do by hand, and nothing an AI writes ever reaches the database without a click from that person.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Invalid, NotFound
from app.models import ActionProposal, User
from app.modules.audit.service import record_event, to_jsonable

LIFETIME = timedelta(minutes=30)
MONEY = r"^\d{1,15}(\.\d{1,2})?$"
QTY = r"^\d{1,12}(\.\d{1,3})?$"


class RequestLineP(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    qty: str = Field(pattern=QTY)
    est_rate: str = Field(pattern=MONEY)


class RequestP(BaseModel):
    category_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    justification: str = Field(default="", max_length=4000)
    cost_center: str = Field(default="", max_length=60)
    lines: list[RequestLineP] = Field(min_length=1, max_length=50)


class SupplierInviteP(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    category: str = Field(max_length=10)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)


class WorkflowDraftP(BaseModel):
    name: str = Field(default="Request approval", max_length=120)
    definition: dict[str, Any]


class RfqLineP(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    qty: str = Field(pattern=QTY)


class RfqP(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category_id: uuid.UUID
    currency: str = Field(default="INR", min_length=3, max_length=3)
    closes_in_days: int = Field(default=7, ge=1, le=60)
    lines: list[RfqLineP] = Field(min_length=1, max_length=50)


SCHEMAS: dict[str, type[BaseModel]] = {"request": RequestP, "supplier_invite": SupplierInviteP,
                                       "workflow_draft": WorkflowDraftP, "rfq": RfqP}


def _hash(kind: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"kind": kind, "payload": payload}, sort_keys=True, default=str).encode()).hexdigest()


def create(db: Session, user: User, kind: str, payload: dict[str, Any], agent: str) -> ActionProposal:
    """Store a proposal after checking its shape. Raises Invalid with the reason a model can read."""
    if kind not in SCHEMAS:
        raise Invalid(f"Unknown proposal kind {kind!r}.")
    try:
        clean = to_jsonable(SCHEMAS[kind].model_validate(payload).model_dump())
    except ValidationError as exc:
        raise Invalid(f"The proposal is not complete: {exc.error_count()} problem(s), e.g. "
                      f"{exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}") from exc
    row = ActionProposal(id=uuid.uuid4(), org_id=user.org_id, user_id=user.id, kind=kind, agent=agent[:20],
                         payload=clean, payload_sha256=_hash(kind, clean), expires_at=datetime.now(UTC) + LIFETIME)
    db.add(row)
    db.flush()
    return row


def as_card(row: ActionProposal) -> dict[str, Any]:
    """What the chat shows: a typed card with a Submit button, never an action already taken."""
    return {"id": row.id, "kind": row.kind, "agent": row.agent, "payload": row.payload,
            "expires_at": row.expires_at, "used": row.used_at is not None}


def load_mine(db: Session, user: User, proposal_id: uuid.UUID) -> ActionProposal:
    # Another person's proposal reads as "not found", also inside the same org.
    row = db.scalar(select(ActionProposal).where(ActionProposal.id == proposal_id, ActionProposal.org_id == user.org_id,
                                                 ActionProposal.user_id == user.id).with_for_update())
    if row is None:
        raise NotFound("Proposal not found.")
    return row


def submit(db: Session, user: User, proposal_id: uuid.UUID) -> dict[str, Any]:
    """The person's click. Runs the normal service function, which re-checks everything."""
    from app.modules.procurement import service as procurement
    from app.modules.sourcing import service as sourcing
    from app.modules.suppliers import service as suppliers
    from app.modules.workflow_engine import service as workflows

    row = load_mine(db, user, proposal_id)
    if row.used_at is not None:
        raise Conflict("This proposal was already submitted.")
    if row.expires_at <= datetime.now(UTC):
        raise Conflict("This proposal has expired. Ask again for a fresh one.")
    if _hash(row.kind, row.payload) != row.payload_sha256:
        raise Conflict("This proposal was changed after it was made, so it cannot be used.")
    p = row.payload
    if row.kind == "request":
        record = procurement.create_request(
            db, user, category_id=uuid.UUID(p["category_id"]), title=p["title"], justification=p["justification"],
            cost_center=p["cost_center"], needed_by=None,
            lines=[procurement.LineInput(l["description"], Decimal(l["qty"]), Decimal(l["est_rate"])) for l in p["lines"]],
            ai_draft={"model_id": f"agent:{row.agent}", "prompt_version": "proposal-v1"})
        result = {"kind": "request", "id": record.id, "href": f"/requests/{record.id}"}
    elif row.kind == "supplier_invite":
        record, token = suppliers.invite(db, user, **p)
        result = {"kind": "supplier", "id": record.id, "href": f"/suppliers/{record.id}", "invite_token": token}
    elif row.kind == "workflow_draft":
        record = workflows.save_draft(db, user, key=workflows.REQUEST_APPROVAL_KEY, name=p["name"],
                                      definition=p["definition"], drafted_by_ai=True)
        result = {"kind": "workflow_draft", "id": record.id, "href": "/automation/workflows"}
    else:
        record = sourcing.create_rfq(db, user, title=p["title"], category_id=uuid.UUID(p["category_id"]),
                                     currency=p["currency"], closes_at=datetime.now(UTC) + timedelta(days=p["closes_in_days"]),
                                     lines=p["lines"], weights=None)
        result = {"kind": "rfq", "id": record.id, "href": f"/sourcing/{record.id}"}
    row.used_at, row.result_id = datetime.now(UTC), record.id
    record_event(db, org_id=user.org_id, entity_type="action_proposal", entity_id=row.id, actor_id=user.id,
                 action="submitted", payload={"kind": row.kind, "agent": row.agent, "sha256": row.payload_sha256,
                                              "result_id": record.id})
    return result
