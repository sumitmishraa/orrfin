"""Step 33 (BUILD_PLAN v3.0 change 43, §5, §6f): RFQs, invited suppliers, sealed quotes and awards.

Additive only. Money NUMERIC(18,2), quantities NUMERIC(18,3), tax rates NUMERIC(7,4).

Revision ID: d0a4c8f6b2e5
Revises: c9f3b7e5a1d4
Create Date: 2026-11-14 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0a4c8f6b2e5"
down_revision: str | None = "c9f3b7e5a1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def base(table: str) -> list:
    """id, org_id and timestamps, as on every business table (§5). Shared with the contracts migration."""
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f(f"fk_{table}_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"))


def index(table: str, *columns: str) -> None:
    for column in ("org_id", *columns):
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def upgrade() -> None:
    op.create_table(
        "rfq_events",
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("scoring", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'open', 'closed', 'awarded', 'cancelled')",
                           name=op.f("ck_rfq_events_status")),
        sa.UniqueConstraint("org_id", "number", name=op.f("uq_rfq_events_org_id")),
        fk("rfq_events", "category_id", "categories"), fk("rfq_events", "created_by", "users"),
        fk("rfq_events", "request_id", "purchase_requests"),
        *base("rfq_events"),
    )
    index("rfq_events")
    op.create_table(
        "rfq_lines",
        sa.Column("rfq_id", sa.UUID(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("uom", sa.String(length=40), server_default="Nos", nullable=False),
        fk("rfq_lines", "rfq_id", "rfq_events"), *base("rfq_lines"),
    )
    index("rfq_lines", "rfq_id")
    op.create_table(
        "rfq_invites",
        sa.Column("rfq_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.UniqueConstraint("rfq_id", "supplier_id", name=op.f("uq_rfq_invites_rfq_id")),
        fk("rfq_invites", "rfq_id", "rfq_events"), fk("rfq_invites", "supplier_id", "suppliers"),
        *base("rfq_invites"),
    )
    index("rfq_invites", "rfq_id", "supplier_id")
    op.create_table(
        "quotes",
        sa.Column("rfq_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("freight", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("delivery_days", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("submitted_by", sa.UUID(), nullable=False),
        sa.UniqueConstraint("rfq_id", "supplier_id", name=op.f("uq_quotes_rfq_id")),
        fk("quotes", "rfq_id", "rfq_events"), fk("quotes", "supplier_id", "suppliers"),
        fk("quotes", "submitted_by", "supplier_users"),
        *base("quotes"),
    )
    index("quotes", "rfq_id")
    op.create_table(
        "quote_lines",
        sa.Column("quote_id", sa.UUID(), nullable=False),
        sa.Column("rfq_line_id", sa.UUID(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.UniqueConstraint("quote_id", "rfq_line_id", name=op.f("uq_quote_lines_quote_id")),
        fk("quote_lines", "quote_id", "quotes"), fk("quote_lines", "rfq_line_id", "rfq_lines"),
        *base("quote_lines"),
    )
    index("quote_lines", "quote_id")
    op.create_table(
        "rfq_awards",
        sa.Column("rfq_id", sa.UUID(), nullable=False),
        sa.Column("quote_id", sa.UUID(), nullable=False),
        sa.Column("awarded_by", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("comparison_snapshot", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("rfq_id", name=op.f("uq_rfq_awards_rfq_id")),
        fk("rfq_awards", "rfq_id", "rfq_events"), fk("rfq_awards", "quote_id", "quotes"),
        fk("rfq_awards", "awarded_by", "users"),
        *base("rfq_awards"),
    )
    index("rfq_awards")


def downgrade() -> None:
    for table in ("rfq_awards", "quote_lines", "quotes", "rfq_invites", "rfq_lines", "rfq_events"):
        op.drop_table(table)
