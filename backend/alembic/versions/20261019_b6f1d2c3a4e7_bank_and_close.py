"""Step 26 (BUILD_PLAN v2.4 change 32; ADR 0008): bank reconciliation and month-end close.

Additive only. bank_statements + bank_lines hold imported statement CSVs (the mock bank's, or any in the
same columns); a line is matched to a paid payment line by rules (UTR first; amount + date + name only as a
suggestion a person accepts). close_periods records each month's close sign-off and any reopening.

Revision ID: b6f1d2c3a4e7
Revises: 9e5a3c7d2f60
Create Date: 2026-10-19 20:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6f1d2c3a4e7"
down_revision: str | None = "9e5a3c7d2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)


def _common(table: str) -> list:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f(f"fk_{table}_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "bank_statements", *_common("bank_statements"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_bank_statements_uploaded_by_users")),
        sa.UniqueConstraint("org_id", "sha256", name=op.f("uq_bank_statements_org_id")),
    )
    op.create_index(op.f("ix_bank_statements_org_id"), "bank_statements", ["org_id"])
    op.create_table(
        "bank_lines", *_common("bank_lines"),
        sa.Column("statement_id", sa.UUID(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("narration", sa.Text(), server_default="", nullable=False),
        sa.Column("reference", sa.String(length=64), server_default="", nullable=False),
        sa.Column("debit", MONEY, server_default="0", nullable=False),
        sa.Column("credit", MONEY, server_default="0", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="unmatched", nullable=False),
        sa.Column("payment_line_id", sa.UUID(), nullable=True),
        sa.Column("match_method", sa.String(length=20), nullable=True),
        sa.Column("matched_by", sa.UUID(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('unmatched', 'suggested', 'matched')", name=op.f("ck_bank_lines_status")),
        sa.ForeignKeyConstraint(["statement_id"], ["bank_statements.id"], name=op.f("fk_bank_lines_statement_id_bank_statements")),
        sa.ForeignKeyConstraint(["payment_line_id"], ["payment_lines.id"], name=op.f("fk_bank_lines_payment_line_id_payment_lines")),
        sa.ForeignKeyConstraint(["matched_by"], ["users.id"], name=op.f("fk_bank_lines_matched_by_users")),
    )
    op.create_index(op.f("ix_bank_lines_org_id"), "bank_lines", ["org_id"])
    op.create_index(op.f("ix_bank_lines_statement_id"), "bank_lines", ["statement_id"])
    # One bank line per payment line once matched (a payment cannot be reconciled twice).
    op.create_index("uq_bank_lines_payment_line", "bank_lines", ["payment_line_id"], unique=True,
                    postgresql_where=sa.text("status = 'matched'"))
    op.create_table(
        "close_periods", *_common("close_periods"),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="open", nullable=False),
        sa.Column("closed_by", sa.UUID(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_notes", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("reopened_by", sa.UUID(), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_close_periods_status")),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], name=op.f("fk_close_periods_closed_by_users")),
        sa.ForeignKeyConstraint(["reopened_by"], ["users.id"], name=op.f("fk_close_periods_reopened_by_users")),
        sa.UniqueConstraint("org_id", "period", name=op.f("uq_close_periods_org_id")),
    )
    op.create_index(op.f("ix_close_periods_org_id"), "close_periods", ["org_id"])


def downgrade() -> None:
    op.drop_table("close_periods")
    op.drop_table("bank_lines")
    op.drop_table("bank_statements")
