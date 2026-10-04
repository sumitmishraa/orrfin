"""SQLAlchemy models for every table in BUILD_PLAN §5 (v2.1), plus `sessions` for login (§3, §9).

Owns the schema only; business rules live in app/modules/*. Conventions (§5):
- every business table has `id` (uuid), `org_id` (indexed), `created_at`, `updated_at`;
- money is NUMERIC(18,2), quantities NUMERIC(18,3), tax rates NUMERIC(7,4); Python sees Decimal;
- status columns are strings with CHECK constraints, not Postgres enums, so later
  migrations can add a value additively (demo-week rule, §10 F).
The Alembic migration in alembic/versions mirrors these definitions.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MONEY = Numeric(18, 2)
QTY = Numeric(18, 3)
TAX_RATE = Numeric(7, 4)

ROLES = ("requester", "buyer", "approver", "finance", "admin")
REQUEST_STATUSES = (
    "draft", "submitted", "with_buyer", "in_approval", "returned",
    "approved", "rejected", "po_drafted", "po_open", "cancelled",
)
DECISIONS = ("approve", "reject", "return")
JOB_STATUSES = ("queued", "running", "done", "failed")
OUTBOX_STATES = ("PENDING", "SENT", "CONFIRMED", "FAILED", "UNKNOWN")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Org(TimestampMixin, Base):
    __tablename__ = "orgs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="role"),
        # Login is by email alone, so an email identifies one user across all orgs.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class UserSession(TimestampMixin, Base):
    """Server-side login session. Only a SHA-256 of the cookie token is stored."""
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("org_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    erp_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ApprovalPolicy(TimestampMixin, Base):
    __tablename__ = "approval_policies"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    min_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_amount: Mapped[Decimal | None] = mapped_column(MONEY)  # NULL = no ceiling
    steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # e.g. ["manager", "finance"]
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class PurchaseRequest(TimestampMixin, Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status"),
        UniqueConstraint("org_id", "number"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # shown as PR-0001
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    cost_center: Mapped[str] = mapped_column(String(60), nullable=False, server_default="")
    needed_by: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    assigned_buyer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    suggested_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    # The buyer who sent it into approval; segregation of duties bars them from approving it (§9).
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # Each (re)start of the approval chain gets a new round; older rounds stay as history.
    approval_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")


class RequestLine(TimestampMixin, Base):
    __tablename__ = "request_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(140))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    est_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    hsn: Mapped[str | None] = mapped_column(String(10))


class RequestApproval(TimestampMixin, Base):
    __tablename__ = "request_approvals"
    __table_args__ = (
        CheckConstraint(_in("decision", DECISIONS), name="decision"),
        UniqueConstraint("request_id", "round", "step"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id"), nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    required_role: Mapped[str] = mapped_column(String(20), nullable=False)  # "manager" = requester's manager_id
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str | None] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "erp_ref"),
        CheckConstraint(_in("origin", ("orrfin", "erp")), name="origin"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    erp_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    po_date: Mapped[date | None] = mapped_column(Date)
    schedule_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    net_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_requests.id"))
    origin: Mapped[str] = mapped_column(String(10), nullable=False, server_default="erp")


class PoLine(TimestampMixin, Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("org_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    hsn: Mapped[str | None] = mapped_column(String(10))
    uom: Mapped[str | None] = mapped_column(String(40))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # unit price, INR
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(TAX_RATE, nullable=False, server_default="0")  # GST %, e.g. 18.0000


class GoodsReceipt(TimestampMixin, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (UniqueConstraint("org_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    erp_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    posting_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False)


class GrnLine(TimestampMixin, Base):
    __tablename__ = "grn_lines"
    __table_args__ = (UniqueConstraint("org_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=False, index=True)
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("po_lines.id"), index=True)
    item_code: Mapped[str] = mapped_column(String(140), nullable=False)
    qty_received: Mapped[Decimal] = mapped_column(QTY, nullable=False)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Duplicate-invoice key (§5). Not unique: a key-only match is a warning, not a block.
        Index("ix_invoices_duplicate_key", "org_id", "vendor_gstin", "invoice_no_norm", "fiscal_year"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"))
    vendor_gstin: Mapped[str | None] = mapped_column(String(15))
    invoice_no: Mapped[str | None] = mapped_column(String(60))
    invoice_no_norm: Mapped[str | None] = mapped_column(String(60))
    invoice_date: Mapped[date | None] = mapped_column(Date)  # document date, IST
    fiscal_year: Mapped[str | None] = mapped_column(String(9))  # e.g. 2026-27
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    subtotal: Mapped[Decimal | None] = mapped_column(MONEY)
    cgst: Mapped[Decimal | None] = mapped_column(MONEY)
    sgst: Mapped[Decimal | None] = mapped_column(MONEY)
    igst: Mapped[Decimal | None] = mapped_column(MONEY)
    total: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="uploaded")
    # Step 7 (additive): fields read from the PDF that matching needs and finance may correct.
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    buyer_gstin: Mapped[str | None] = mapped_column(String(15))
    po_reference: Mapped[str | None] = mapped_column(String(140))  # the buyer's PO number as printed
    place_of_supply: Mapped[str | None] = mapped_column(String(2))  # GST state code, e.g. 27
    # Step 7 (additive): why extraction fell back to manual entry, and who confirmed the fields.
    extraction_error: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    item_code: Mapped[str | None] = mapped_column(String(140))
    hsn: Mapped[str | None] = mapped_column(String(10))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("po_lines.id"))
    pairing_method: Mapped[str | None] = mapped_column(String(30))


class Extraction(TimestampMixin, Base):
    __tablename__ = "extractions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    field_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FieldEdit(TimestampMixin, Base):
    __tablename__ = "field_edits"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(80), nullable=False)
    old: Mapped[str | None] = mapped_column(Text)
    new: Mapped[str | None] = mapped_column(Text)
    edited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class MatchResult(TimestampMixin, Base):
    __tablename__ = "match_results"
    __table_args__ = (CheckConstraint(_in("outcome", ("matched", "exception", "stale")), name="outcome"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    rule_set_version: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_at_risk: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rule_results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # Step 8 (additive): fixed-weight risk score (0-100) and the plain-English explanation,
    # written from rule_results only (by Claude, or by a template when AI is unavailable).
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str | None] = mapped_column(String(60))


class ReviewDecision(TimestampMixin, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(_in("decision", ("approve", "reject", "request_correction")), name="decision"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        # The worker's claim query scans queued jobs by run_after.
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErpOutbox(TimestampMixin, Base):
    __tablename__ = "erp_outbox"
    __table_args__ = (
        CheckConstraint(_in("state", OUTBOX_STATES), name="state"),
        CheckConstraint(_in("doc_type", ("purchase_invoice", "purchase_order")), name="doc_type"),
        # Exactly one source document per outbox row (§5).
        CheckConstraint("(invoice_id IS NULL) <> (request_id IS NULL)", name="one_source"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_requests.id"))
    state: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    erp_doc_name: Mapped[str | None] = mapped_column(String(140))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    """Append-only, hash-chained per entity (§2, §5). No updated_at: rows never change.

    The app database role has INSERT and SELECT only on this table (migration grants).
    """
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("entity_id", "seq"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
