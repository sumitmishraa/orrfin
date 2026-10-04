"""Request and response shapes for invoice routes (BUILD_PLAN §5 invoices, §7 review form).

Money is a decimal string ("54870.00") in both directions; never a float.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    status: str
    filename: str
    vendor_name: str | None
    invoice_no: str | None
    invoice_date: date | None
    po_reference: str | None
    total: Decimal | None
    outcome: str | None = None  # Step 8: matched | exception | stale
    amount_at_risk: Decimal | None = None
    risk_score: int | None = None
    created_at: datetime


class InvoiceLineOut(BaseModel):
    line_no: int
    description: str
    item_code: str | None
    hsn: str | None
    qty: Decimal
    rate: Decimal
    amount: Decimal
    po_line_id: uuid.UUID | None
    pairing_method: str | None


class IssueOut(BaseModel):
    field: str
    code: str
    message: str


class ExtractionOut(BaseModel):
    model_id: str
    prompt_version: str
    confidence: str | None
    finished_at: datetime | None
    simulated: bool  # True when the answer-key stand-in produced it, not an AI model


class FieldEditOut(BaseModel):
    field: str
    old: str | None
    new: str | None
    edited_by_name: str
    at: datetime


class TimelineEventOut(BaseModel):
    seq: int
    action: str
    actor_name: str | None
    at: datetime
    payload: dict[str, Any]


class InvoiceAllowed(BaseModel):
    edit: bool = False
    confirm: bool = False
    decide: bool = False  # Step 9
    approve_blocked_reason: str | None = None  # Step 9


class InvoiceDetail(InvoiceSummary):
    vendor_gstin: str | None
    buyer_gstin: str | None
    place_of_supply: str | None
    currency: str
    subtotal: Decimal | None
    cgst: Decimal | None
    sgst: Decimal | None
    igst: Decimal | None
    uploaded_by_name: str
    confirmed_by_name: str | None
    confirmed_at: datetime | None
    extraction_error: str | None
    lines: list[InvoiceLineOut]
    issues: list[IssueOut]
    evidence: dict[str, Any]
    extraction: ExtractionOut | None
    edits: list[FieldEditOut]
    timeline: list[TimelineEventOut]
    allowed: InvoiceAllowed
    match: dict[str, Any] | None = None  # Step 8: rule results, explanation, PO / receipt comparison
    decisions: list[dict[str, Any]] = Field(default_factory=list)  # Step 9


class LineEdit(BaseModel):
    description: str | None = None
    item_code: str | None = None
    hsn: str | None = None
    qty: str | None = None
    rate: str | None = None
    amount: str | None = None


class InvoiceEdit(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict)
    lines: list[LineEdit] | None = Field(default=None, max_length=100)


class ConfirmIn(BaseModel):
    acknowledge_issues: bool = False
