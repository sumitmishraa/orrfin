"""Request and response shapes for procurement routes (BUILD_PLAN §5 request tables).

Money travels as Decimal (serialised as a string such as "240000.00"), never as float.
Inputs are bounded to the column sizes: quantities 3 decimals, rates and amounts 2.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Qty = Annotated[Decimal, Field(gt=0, max_digits=15, decimal_places=3)]
Rate = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    buyer_id: uuid.UUID | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    role: str


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    qty: Qty
    est_rate: Rate
    hsn: str | None = Field(default=None, max_length=10)


class RequestCreate(BaseModel):
    category_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    justification: str = Field(default="", max_length=4000)
    cost_center: str = Field(default="", max_length=60)
    needed_by: date | None = None
    suggested_vendor_id: uuid.UUID | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=50)


class RequestEdit(BaseModel):
    category_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    justification: str | None = Field(default=None, max_length=4000)
    cost_center: str | None = Field(default=None, max_length=60)
    needed_by: date | None = None
    lines: list[LineIn] | None = Field(default=None, min_length=1, max_length=50)


class BuyerLineIn(BaseModel):
    id: uuid.UUID
    item_code: str = Field(max_length=140)
    qty: Qty
    est_rate: Rate
    hsn: str | None = Field(default=None, max_length=10)


class BuyerUpdate(BaseModel):
    vendor_id: uuid.UUID | None = None
    lines: list[BuyerLineIn] = Field(default_factory=list, max_length=50)


class AssignBuyer(BaseModel):
    buyer_id: uuid.UUID


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "return"]
    reason: str | None = Field(default=None, max_length=2000)


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    description: str
    item_code: str | None
    qty: Decimal
    est_rate: Decimal
    amount: Decimal
    hsn: str | None


class StepOut(BaseModel):
    step: int
    required_role: str
    approver_id: uuid.UUID | None
    approver_name: str | None
    decision: str | None
    reason: str | None
    decided_at: datetime | None


class TimelineEvent(BaseModel):
    seq: int
    action: str
    actor_name: str | None
    at: datetime
    payload: dict[str, Any]


class AllowedActions(BaseModel):
    """What the logged-in user may do now. The server re-checks every action anyway."""
    edit: bool = False
    submit: bool = False
    assign_buyer: bool = False
    buyer_edit: bool = False
    send_for_approval: bool = False
    decide_step: int | None = None  # the step they may approve, reject or return
    can_approve: bool = False  # False when e.g. the amount is above their limit
    approve_blocked_reason: str | None = None


class RequestSummary(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    status: str
    amount: Decimal
    currency: str
    category_name: str
    requester_name: str
    buyer_name: str | None
    needed_by: date | None
    created_at: datetime
    updated_at: datetime
    waiting_on: str | None  # e.g. "Step 2: finance"


class RequestDetail(RequestSummary):
    justification: str
    cost_center: str
    category_id: uuid.UUID
    requested_by: uuid.UUID
    assigned_buyer_id: uuid.UUID | None
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    suggested_vendor_id: uuid.UUID | None
    suggested_vendor_name: str | None
    completed_by_id: uuid.UUID | None
    approval_round: int
    ready_for_po: bool
    lines: list[LineOut]
    current_steps: list[StepOut]
    timeline: list[TimelineEvent]
    allowed: AllowedActions
