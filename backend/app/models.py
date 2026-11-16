"""SQLAlchemy models for every table in BUILD_PLAN §5 (v2.2), plus `sessions` for login (§3, §9).

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
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
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
# Step 42 (ADR 0012): who prices a request. "buyer_first" (Steps 4-41): the buyer adds vendor and rates,
# then the amount tiers approve the request. "need_first": the employee states only the need, their
# manager approves it, and procurement prices approved needs on a combined PO that Finance approves.
INTAKE_FLOWS = ("buyer_first", "need_first")
REQUEST_CHANNELS = ("form", "whatsapp", "email")
ORDER_PO_STATUSES = ("draft", "in_approval", "returned", "approved", "rejected", "sent", "cancelled")
VENDOR_MESSAGE_CHANNELS = ("email", "whatsapp")
JOB_STATUSES = ("queued", "running", "done", "failed")
OUTBOX_STATES = ("PENDING", "SENT", "CONFIRMED", "FAILED", "UNKNOWN")
CONNECTION_MODES = ("simulated", "live")
CONNECTION_STATUSES = ("not_connected", "connected", "error")


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
    __table_args__ = (CheckConstraint(_in("intake_flow", INTAKE_FLOWS), name="intake_flow"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Step 41 (ADR 0011): the workspace's simulated plan. Requesters are free and unlimited; buyer,
    # approver, finance and admin each use one "power seat". No real billing exists.
    plan_name: Mapped[str] = mapped_column(String(40), nullable=False, server_default="Growth")
    power_seat_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    # Step 42 (ADR 0012): see INTAKE_FLOWS. Existing orgs keep "buyer_first"; the demo org uses "need_first".
    intake_flow: Mapped[str] = mapped_column(String(20), nullable=False, server_default="buyer_first")


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
    # v3.0 (§9): two-step sign-in. The TOTP secret is a Fernet token; the last step used blocks replays.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger)
    # Step 41: team management. Who invited this person, their department, and when they were last seen.
    department: Mapped[str | None] = mapped_column(String(80))
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def mfa_enabled(self) -> bool:
        return self.mfa_enabled_at is not None


class UserSession(TimestampMixin, Base):
    """Server-side login session. Only a SHA-256 of the cookie token is stored."""
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamInvite(TimestampMixin, Base):
    """An invitation for a new team member (Step 41, ADR 0011, §9).

    Single-use: only a SHA-256 of the token is stored and it expires in 7 days. The `users` row is
    created only when the invitation is accepted, so a pending invite never holds a login.
    """
    __tablename__ = "team_invites"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="role"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    department: Mapped[str | None] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginThrottle(TimestampMixin, Base):
    """Wrong-password counter per email (auth/throttle.py, §9). Holds a hash of the email only.

    No org_id on purpose: it is written before anyone is logged in, also for unknown emails.
    """
    __tablename__ = "login_throttles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))



class ErpConnection(TimestampMixin, Base):
    """One way an org can reach one ERP: simulated (fixtures) or live (its own keys). §5 v2.2, ADR 0004/0006.

    Exactly one connection per org is active; sync, invoice matching and write-back all use it.
    Credentials are one Fernet token (app/security/secrets.py); the browser never sees them.
    """
    __tablename__ = "erp_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "system", "mode"),
        CheckConstraint(_in("mode", CONNECTION_MODES), name="mode"),
        CheckConstraint(_in("status", CONNECTION_STATUSES), name="status"),
        Index("uq_erp_connections_one_active", "org_id", unique=True, postgresql_where=text("is_active")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    system: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_connected")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)


def _conn_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("erp_connections.id"), nullable=False, index=True)


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("org_id", "erp_connection_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # Which ERP connection this mirrored row came from (§5 v2.2): two ERPs may reuse a ref.
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
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
    # Step 22 (additive): an extra named approval step for this category, after the amount tiers,
    # e.g. "IT security review" for software that touches customer data (Zip's conditional approver).
    extra_approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    extra_step_label: Mapped[str | None] = mapped_column(String(80))


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
        CheckConstraint(_in("source_channel", REQUEST_CHANNELS), name="source_channel"),
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
    # v3.0 (additive): the legal entity buying; NULL means the org's default entity.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("legal_entities.id"))
    # v3.0 intake forms (additive): the type it was raised as and the answers to that type's questions.
    request_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("request_types.id"))
    custom_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Step 42 (additive): how the need reached Orrfin. A WhatsApp or email message is kept word for word,
    # and `entered_by_id` is set when a manager or procurement typed it in for the employee (who then
    # checks and submits it themselves, so the requester is still the one who asks).
    source_channel: Mapped[str] = mapped_column(String(10), nullable=False, server_default="form")
    source_message: Mapped[str | None] = mapped_column(Text)
    entered_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


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
    unit: Mapped[str | None] = mapped_column(String(20))  # Step 42: "box", "pcs", "ream"; free text


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
    # Step 22 (additive): for a category step (required_role "category_reviewer"), the named person
    # and label, copied when the chain starts so later category edits never change a running chain.
    designated_approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    step_label: Mapped[str | None] = mapped_column(String(80))


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "erp_connection_id", "erp_ref"),
        CheckConstraint(_in("origin", ("orrfin", "erp")), name="origin"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # Which ERP connection this mirrored row came from (§5 v2.2): two ERPs may reuse a ref.
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
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
    # The PO number printed on invoices when the ERP names its record differently (ports/erp.py).
    po_number: Mapped[str | None] = mapped_column(String(140), index=True)
    # Step 42: the Orrfin PO this ERP order was drafted from (it may cover several requests).
    order_po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("order_pos.id"))


class PoLine(TimestampMixin, Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("org_id", "erp_connection_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # Which ERP connection this mirrored row came from (§5 v2.2): two ERPs may reuse a ref.
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
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
    __table_args__ = (UniqueConstraint("org_id", "erp_connection_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # Which ERP connection this mirrored row came from (§5 v2.2): two ERPs may reuse a ref.
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
    erp_ref: Mapped[str] = mapped_column(String(140), nullable=False)
    erp_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    posting_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False)


class GrnLine(TimestampMixin, Base):
    __tablename__ = "grn_lines"
    __table_args__ = (UniqueConstraint("org_id", "erp_connection_id", "erp_ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # Which ERP connection this mirrored row came from (§5 v2.2): two ERPs may reuse a ref.
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
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
    # v3.0 (additive, §6d): the entity it was matched for, and the single tax amount of a UAE invoice.
    # `vendor_gstin` / `buyer_gstin` hold the tax number whatever the regime (GSTIN or TRN).
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("legal_entities.id"))
    vat: Mapped[Decimal | None] = mapped_column(MONEY)


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
        CheckConstraint("num_nonnulls(invoice_id, request_id, order_po_id) = 1", name="one_source"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    # The ERP this document is written to; fixed when the row is created (§8).
    erp_connection_id: Mapped[uuid.UUID] = _conn_fk()
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_requests.id"))
    # Step 42: a combined PO built from several approved needs (one ERP draft PO for all of them).
    order_po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("order_pos.id"))
    state: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    erp_doc_name: Mapped[str | None] = mapped_column(String(140))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)


class OrderPo(TimestampMixin, Base):
    """Step 42 (ADR 0012): a purchase order procurement builds in Orrfin from approved needs.

    Orrfin owns it until its ERP draft is confirmed (§2); the ERP's PO is then the order of record.
    Shown to people as PO-0001. Lines may merge the same item from several requests.
    """
    __tablename__ = "order_pos"
    __table_args__ = (
        CheckConstraint(_in("status", ORDER_PO_STATUSES), name="status"),
        UniqueConstraint("org_id", "number"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    needed_by: Mapped[date | None] = mapped_column(Date)
    note_to_vendor: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    approval_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The person who sent it for approval; segregation of duties bars them from approving it (§9).
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class OrderPoLine(TimestampMixin, Base):
    __tablename__ = "order_po_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    order_po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_pos.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    hsn: Mapped[str | None] = mapped_column(String(10))


class OrderPoLineSource(TimestampMixin, Base):
    """Which request line a PO line orders. `active` turns false when the PO is cancelled or rejected,
    which frees the request line; the partial unique index allows only one live PO per request line."""
    __tablename__ = "order_po_line_sources"
    __table_args__ = (
        Index("uq_order_po_line_sources_live_request_line", "request_line_id", unique=True,
              postgresql_where=text("active")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    order_po_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_po_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    request_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_lines.id"), nullable=False, index=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id"), nullable=False, index=True)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class OrderPoApproval(TimestampMixin, Base):
    __tablename__ = "order_po_approvals"
    __table_args__ = (
        CheckConstraint(_in("decision", DECISIONS), name="decision"),
        UniqueConstraint("order_po_id", "round", "step"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    order_po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_pos.id"), nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    required_role: Mapped[str] = mapped_column(String(20), nullable=False)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str | None] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VendorMessage(TimestampMixin, Base):
    """Step 42: the PO as sent to the vendor. Simulated: Orrfin records and shows it but sends nothing."""
    __tablename__ = "vendor_messages"
    __table_args__ = (CheckConstraint(_in("channel", VENDOR_MESSAGE_CHANNELS), name="channel"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    order_po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_pos.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_name: Mapped[str | None] = mapped_column(String(200))
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


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


class OrgSettings(TimestampMixin, Base):
    """Per-org workflow settings (Step 22). A missing row means the defaults below."""
    __tablename__ = "org_settings"
    __table_args__ = (CheckConstraint("approval_sla_hours BETWEEN 1 AND 720", name="sla"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, unique=True)
    # An approval step waiting longer than this is "overdue" and can be nudged.
    approval_sla_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="48")


class ExceptionTask(TimestampMixin, Base):
    """A held invoice's question to a named person (Step 22; Zip "hold and ask the requester").

    While a task is open the invoice cannot be approved; the person asked can never approve it.
    """
    __tablename__ = "exception_tasks"
    __table_args__ = (CheckConstraint(_in("status", ("open", "answered", "closed")), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    asked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Budget(TimestampMixin, Base):
    """Budget for one cost centre in one financial-year quarter (Step 22). Warnings only, never a block."""
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("org_id", "cost_center", "fiscal_year", "quarter"),
        CheckConstraint("quarter BETWEEN 1 AND 4", name="quarter"),
        CheckConstraint("amount >= 0", name="amount"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    cost_center: Mapped[str] = mapped_column(String(60), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(9), nullable=False)  # e.g. 2026-27
    quarter: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 = Apr–Jun … 4 = Jan–Mar
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class AssistantTurn(TimestampMixin, Base):
    """One assistant question and answer (Step 23, ADR 0007). A log, not an audit event: asking changes nothing."""
    __tablename__ = "assistant_turns"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Tool names and arguments only, not results: enough to replay what the assistant looked at.
    tool_calls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    answer: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    grounded: Mapped[bool | None] = mapped_column(Boolean)  # every ₹ figure found in the tool results
    error: Mapped[str | None] = mapped_column(Text)


class VendorPaymentProfile(TimestampMixin, Base):
    """Orrfin-owned payment details for a vendor (Step 25, ADR 0008). The vendor master stays in the ERP.

    Maker-checker: whoever changes the bank details cannot verify them; until verified, payments block.
    """
    __tablename__ = "vendor_payment_profiles"
    __table_args__ = (UniqueConstraint("org_id", "vendor_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    pan: Mapped[str | None] = mapped_column(String(10))
    tds_section: Mapped[str | None] = mapped_column(String(4))  # 194C, 194J, 194Q or none
    payee_type: Mapped[str] = mapped_column(String(12), nullable=False, server_default="company")
    j_kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="professional")
    account_name: Mapped[str] = mapped_column(String(140), nullable=False)
    bank_account: Mapped[str] = mapped_column(String(34), nullable=False)  # Indian account number, or an IBAN
    ifsc: Mapped[str | None] = mapped_column(String(11))  # Indian payees (NEFT/RTGS)
    swift_bic: Mapped[str | None] = mapped_column(String(11))  # v3.0: international payees, with an IBAN
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending_verification")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentRun(TimestampMixin, Base):
    """A batch of simulated payments (Step 25): draft → submitted → approved → sent → settled / partly_failed."""
    __tablename__ = "payment_runs"
    __table_args__ = (UniqueConstraint("org_id", "number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # shown as PAY-0001
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")  # v3.0: one currency per run
    prepared_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_reason: Mapped[str | None] = mapped_column(Text)  # the approver's reason for paying despite holds
    total_gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    total_tds: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    total_net: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    bank_file_sha256: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentLine(TimestampMixin, Base):
    __tablename__ = "payment_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payment_runs.id"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tds_base: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    tds_section: Mapped[str | None] = mapped_column(String(4))
    tds_rate: Mapped[Decimal] = mapped_column(TAX_RATE, nullable=False, server_default="0")
    tds_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    net: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    risk_results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    risk_rule_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    tds_rule_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    utr: Mapped[str | None] = mapped_column(String(32))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankStatement(TimestampMixin, Base):
    """An imported bank statement CSV (Step 26). The same file twice is refused (sha256 per org)."""
    __tablename__ = "bank_statements"
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class BankLine(TimestampMixin, Base):
    """One statement line and its reconciliation state: unmatched, suggested (a person must accept) or matched."""
    __tablename__ = "bank_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bank_statements.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reference: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    debit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    credit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="unmatched")
    payment_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payment_lines.id"))
    match_method: Mapped[str | None] = mapped_column(String(20))
    matched_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClosePeriod(TimestampMixin, Base):
    """A month's close sign-off (Step 26). A closed month refuses approvals dated in it until reopened."""
    __tablename__ = "close_periods"
    __table_args__ = (UniqueConstraint("org_id", "period"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # e.g. 2026-10
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="open")
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_notes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reopen_reason: Mapped[str | None] = mapped_column(Text)


class Gstr2bImport(TimestampMixin, Base):
    """One imported GSTR-2B statement (Step 27). Matching only: Orrfin files nothing with GSTN."""
    __tablename__ = "gstr2b_imports"
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # e.g. 2026-09
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class Gstr2bLine(TimestampMixin, Base):
    """A supplier invoice as reported in GSTR-2B, and how it matched Orrfin's books."""
    __tablename__ = "gstr2b_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gstr2b_imports.id"), nullable=False, index=True)
    supplier_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    invoice_no: Mapped[str] = mapped_column(String(60), nullable=False)
    invoice_no_norm: Mapped[str] = mapped_column(String(60), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(9), nullable=False)
    invoice_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    igst: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    cgst: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    sgst: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    itc_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))


# --- Workflow engine (BUILD_PLAN v3.0 change 39, ADR 0010) ---------------------------------------

WORKFLOW_VERSION_STATUSES = ("draft", "published", "retired")


class WorkflowDefinition(TimestampMixin, Base):
    """One named workflow of an org, e.g. "request-approval". Its steps live in its versions."""
    __tablename__ = "workflow_definitions"
    __table_args__ = (UniqueConstraint("org_id", "key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # The version now in use, or NULL while only drafts exist. Not a foreign key: versions point
    # at their definition already, and a two-way key would make the first insert impossible.
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class WorkflowVersion(TimestampMixin, Base):
    """One saved set of steps. Once published it is never edited: a change is a new version."""
    __tablename__ = "workflow_versions"
    __table_args__ = (
        CheckConstraint(_in("status", WORKFLOW_VERSION_STATUSES), name="status"),
        UniqueConstraint("definition_id", "number"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # SHA-256 of the definition, written into the publish audit event: proof of exactly what went live.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="draft")
    drafted_by_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Supplier onboarding, portal realm and risk (BUILD_PLAN v3.0 changes 41-42, §5, §6e) ---------

SUPPLIER_STATUSES = ("invited", "submitted", "in_review", "approved", "rejected", "handed_over", "active")
SUPPLIER_DOCUMENT_KINDS = ("tax_certificate", "pan", "bank_proof", "other")
RISK_LEVELS = ("low", "medium", "high", "critical")


def _supplier_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False, index=True)


class Supplier(TimestampMixin, Base):
    """An onboarding record Orrfin owns until handover. The vendor itself lives in the ERP (`vendor_id`)."""
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint(_in("status", SUPPLIER_STATUSES), name="status"),
        CheckConstraint(_in("country", ("IN", "AE")), name="country"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    category: Mapped[str] = mapped_column(String(10), nullable=False)  # goods, services or software
    tax_id: Mapped[str | None] = mapped_column(String(15))  # GSTIN or TRN
    pan: Mapped[str | None] = mapped_column(String(10))
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="invited")
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    # Segregation of duties (§9): the inviter may not review this supplier.
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Bank details: one Fernet token; the page shows the last four characters only.
    bank_details_encrypted: Mapped[str | None] = mapped_column(Text)
    bank_last4: Mapped[str | None] = mapped_column(String(4))
    bank_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    bank_changed_on: Mapped[date | None] = mapped_column(Date)
    # §6e: a critical risk level holds new POs and payments until a named reviewer clears it.
    on_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class SupplierUser(TimestampMixin, Base):
    """A supplier's contact who signs in to the portal. A separate login realm from `users` (§9)."""
    __tablename__ = "supplier_users"
    __table_args__ = (Index("uq_supplier_users_email_lower", text("lower(email)"), unique=True),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    supplier_id: Mapped[uuid.UUID] = _supplier_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # NULL until the invitation is accepted
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class SupplierInvite(TimestampMixin, Base):
    """A single-use invitation link. Only a SHA-256 of the token is stored; it expires in 7 days."""
    __tablename__ = "supplier_invites"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    supplier_id: Mapped[uuid.UUID] = _supplier_fk()
    supplier_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupplierSession(TimestampMixin, Base):
    """A portal login session. Its own table and cookie, so it can never pass as an employee session."""
    __tablename__ = "supplier_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    supplier_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupplierDocument(TimestampMixin, Base):
    """A file a supplier uploaded. It keeps its own file fields: `documents.uploaded_by` must be an employee."""
    __tablename__ = "supplier_documents"
    __table_args__ = (CheckConstraint(_in("kind", SUPPLIER_DOCUMENT_KINDS), name="kind"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    supplier_id: Mapped[uuid.UUID] = _supplier_fk()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)


class RiskAssessment(TimestampMixin, Base):
    """One run of the §6e rules, kept with its rule-set version so the result can be re-explained."""
    __tablename__ = "risk_assessments"
    __table_args__ = (CheckConstraint(_in("level", RISK_LEVELS), name="level"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    supplier_id: Mapped[uuid.UUID] = _supplier_fk()
    rule_set_version: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    next_review_on: Mapped[date | None] = mapped_column(Date)


class SanctionsEntry(TimestampMixin, Base):
    """A name on the synthetic sanctions list. Reference data shared by all orgs, so no org_id."""
    __tablename__ = "sanctions_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    list_name: Mapped[str] = mapped_column(String(80), nullable=False)


# --- Sourcing (BUILD_PLAN v3.0 change 43, §5, §6f) ------------------------------------------------

RFQ_STATUSES = ("draft", "open", "closed", "awarded", "cancelled")


def _rfq_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("rfq_events.id"), nullable=False, index=True)


class RfqEvent(TimestampMixin, Base):
    """A request for quotation. Its scoring weights are fixed when it opens and shown to everyone."""
    __tablename__ = "rfq_events"
    __table_args__ = (UniqueConstraint("org_id", "number"), CheckConstraint(_in("status", RFQ_STATUSES), name="status"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # shown as RFQ-0001
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="draft")
    scoring: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_requests.id"))


class RfqLine(TimestampMixin, Base):
    __tablename__ = "rfq_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rfq_id: Mapped[uuid.UUID] = _rfq_fk()
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str] = mapped_column(String(40), nullable=False, server_default="Nos")


class RfqInvite(TimestampMixin, Base):
    __tablename__ = "rfq_invites"
    __table_args__ = (UniqueConstraint("rfq_id", "supplier_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rfq_id: Mapped[uuid.UUID] = _rfq_fk()
    supplier_id: Mapped[uuid.UUID] = _supplier_fk()


class Quote(TimestampMixin, Base):
    """One supplier's sealed answer to an RFQ: nobody at the buyer sees it until the RFQ closes."""
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("rfq_id", "supplier_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rfq_id: Mapped[uuid.UUID] = _rfq_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    freight: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier_users.id"), nullable=False)


class QuoteLine(TimestampMixin, Base):
    __tablename__ = "quote_lines"
    __table_args__ = (UniqueConstraint("quote_id", "rfq_line_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id"), nullable=False, index=True)
    rfq_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rfq_lines.id"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(TAX_RATE, nullable=False)


class RfqAward(TimestampMixin, Base):
    """Who awarded which quote, why, and the exact comparison they saw."""
    __tablename__ = "rfq_awards"
    __table_args__ = (UniqueConstraint("rfq_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rfq_events.id"), nullable=False)
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id"), nullable=False)
    awarded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    comparison_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# --- Contracts (BUILD_PLAN v3.0 change 44, §5) ----------------------------------------------------

CONTRACT_STATUSES = ("draft", "active", "expired", "terminated")
TERM_FIELDS = ("party", "value", "currency", "start_date", "end_date", "renewal", "notice_days", "payment_terms",
               "liability_cap", "governing_law")


class Contract(TimestampMixin, Base):
    __tablename__ = "contracts"
    __table_args__ = (CheckConstraint(_in("status", CONTRACT_STATUSES), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="draft")
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ContractTerm(TimestampMixin, Base):
    """One key term. AI may propose it with a quote from the document; only a person confirms it."""
    __tablename__ = "contract_terms"
    __table_args__ = (UniqueConstraint("contract_id", "field"), CheckConstraint(_in("source", ("ai", "human")), name="source"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"quote": "...", "page": 2}
    source: Mapped[str] = mapped_column(String(5), nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ContractObligation(TimestampMixin, Base):
    __tablename__ = "contract_obligations"
    __table_args__ = (CheckConstraint(_in("status", ("open", "done")), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(5), nullable=False, server_default="open")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")  # manual | renewal_notice


# --- App Studio (BUILD_PLAN v3.0 change 49) -------------------------------------------------------

class AppObject(TimestampMixin, Base):
    """An admin-built record type: questions, who approves, which columns the list shows. Data, never code."""
    __tablename__ = "app_objects"
    __table_args__ = (UniqueConstraint("org_id", "key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(10), nullable=False)
    list_columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class AppRecord(TimestampMixin, Base):
    """One record of an App Studio object, decided by its approver role (never by its creator)."""
    __tablename__ = "app_records"
    __table_args__ = (CheckConstraint(_in("status", ("submitted", "approved", "rejected")), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_objects.id"), nullable=False, index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


# --- AI layer (BUILD_PLAN v3.0 change 47, ADR 0007) -----------------------------------------------

class ActionProposal(TimestampMixin, Base):
    """Something an AI suggested. Only its own person can submit it, once, before it expires."""
    __tablename__ = "action_proposals"
    __table_args__ = (CheckConstraint(_in("kind", ("request", "supplier_invite", "workflow_draft", "rfq")), name="kind"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    agent: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AgentRun(TimestampMixin, Base):
    """One superagent run, in the app or over MCP: which tools it used and which proposals it made."""
    __tablename__ = "agent_runs"
    __table_args__ = (CheckConstraint(_in("channel", ("chat", "mcp")), name="channel"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(5), nullable=False)
    tools_used: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    proposal_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)


# --- Vendor cards, simulated (BUILD_PLAN v3.0 change 46, ADR 0008) --------------------------------

class VendorCard(TimestampMixin, Base):
    """A simulated virtual card for one approved request. Only the issuer's reference and last four are kept."""
    __tablename__ = "vendor_cards"
    __table_args__ = (CheckConstraint(_in("status", ("active", "frozen", "closed")), name="status"),
                      CheckConstraint("spent <= limit_amount", name="within_limit"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_requests.id"), nullable=False)
    holder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    issued_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    issuer_ref: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    spent: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    merchant_lock: Mapped[str | None] = mapped_column(String(120))
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="active")


class CardTransaction(TimestampMixin, Base):
    """Every charge attempt on a card, approved or declined, with the reason."""
    __tablename__ = "card_transactions"
    __table_args__ = (CheckConstraint(_in("status", ("approved", "declined")), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_cards.id"), nullable=False, index=True)
    merchant: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(9), nullable=False)
    decline_reason: Mapped[str | None] = mapped_column(String(200))
    auth_code: Mapped[str | None] = mapped_column(String(12))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"))


# --- Notifications, API keys, webhooks (BUILD_PLAN v3.0 §5) --------------------------------------

WEBHOOK_DELIVERY_STATUSES = ("pending", "delivered", "failed")


class Notification(TimestampMixin, Base):
    """One message for one person, shown under the bell and copied to email."""
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    link: Mapped[str | None] = mapped_column(String(300))  # a path inside Orrfin, never another site
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(TimestampMixin, Base):
    """A personal API key. Only its SHA-256 is stored; the key itself is shown once."""
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # first characters, to recognise a key
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(TimestampMixin, Base):
    """An https address another system gave us, and the events it wants. The secret is a Fernet token."""
    __tablename__ = "webhook_endpoints"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class WebhookDelivery(TimestampMixin, Base):
    """One event sent (or being sent) to one endpoint, with what the receiver answered."""
    __tablename__ = "webhook_deliveries"
    __table_args__ = (CheckConstraint(_in("status", WEBHOOK_DELIVERY_STATUSES), name="status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)


# --- Intake forms (BUILD_PLAN v3.0 change 40, §5) ------------------------------------------------

FORM_FIELD_KINDS = ("text", "number", "money", "date", "choice", "user")


class RequestType(TimestampMixin, Base):
    """A kind of purchase request ("Software purchase") with its own extra questions."""
    __tablename__ = "request_types"
    __table_args__ = (UniqueConstraint("org_id", "key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    key: Mapped[str] = mapped_column(String(40), nullable=False)  # never changes: workflow rules name it
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    workflow_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class FormField(TimestampMixin, Base):
    """One extra question on a request type's form. Answers are stored on the request as text."""
    __tablename__ = "form_fields"
    __table_args__ = (
        UniqueConstraint("request_type_id", "key"),
        CheckConstraint(_in("kind", FORM_FIELD_KINDS), name="kind"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    request_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_types.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)


# --- Legal entities and exchange rates (BUILD_PLAN v3.0 change 38, §5, §6d) ----------------------

TAX_REGIMES = ("in_gst", "ae_vat")
CURRENCIES = ("INR", "AED", "USD", "EUR")
FX_RATE = Numeric(18, 8)


class LegalEntity(TimestampMixin, Base):
    """One company of the org that buys and is billed. Its tax regime decides how invoices are checked (§6d)."""
    __tablename__ = "legal_entities"
    __table_args__ = (
        UniqueConstraint("org_id", "name"),
        CheckConstraint(_in("tax_regime", TAX_REGIMES), name="tax_regime"),
        CheckConstraint(_in("base_currency", CURRENCIES), name="base_currency"),
        # Documents without an entity belong to this one, so there is exactly one per org.
        Index("uq_legal_entities_one_default", "org_id", unique=True, postgresql_where=text("is_default")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # IN or AE
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_regime: Mapped[str] = mapped_column(String(10), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(15))  # GSTIN in India, TRN in the UAE
    state_code: Mapped[str | None] = mapped_column(String(2))  # GST state code; India only
    erp_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("erp_connections.id"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class EntityMembership(TimestampMixin, Base):
    """A person who works for an entity. An entity with no members is open to the whole org."""
    __tablename__ = "entity_memberships"
    __table_args__ = (UniqueConstraint("entity_id", "user_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class FxRate(TimestampMixin, Base):
    """1 base = `rate` quote on `as_of`, typed in by a named person. Rows are never updated."""
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("org_id", "base_currency", "quote_currency", "as_of"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base_currency <> quote_currency", name="two_currencies"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(FX_RATE, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
