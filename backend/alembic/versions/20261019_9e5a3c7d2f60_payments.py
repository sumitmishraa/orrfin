"""Step 25 (BUILD_PLAN v2.4 change 31, §6b, §6c; ADR 0008): simulated payments.

Additive only. Three new tables:
- vendor_payment_profiles: Orrfin-owned payment details per vendor (PAN, TDS section, bank account,
  IFSC). A bank-detail change needs a second person to verify it (maker-checker).
- payment_runs: a batch of payments prepared, approved and sent to a mock bank. No real money moves.
- payment_lines: one invoice in a run, with gross, TDS, net, the risk-rule results, and the UTR or
  failure reason from the mock bank.

Revision ID: 9e5a3c7d2f60
Revises: 8d4f2b6c1e50
Create Date: 2026-10-19 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e5a3c7d2f60"
down_revision: str | None = "8d4f2b6c1e50"
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
        "vendor_payment_profiles", *_common("vendor_payment_profiles"),
        sa.Column("vendor_id", sa.UUID(), nullable=False),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("tds_section", sa.String(length=4), nullable=True),
        sa.Column("payee_type", sa.String(length=12), server_default="company", nullable=False),
        sa.Column("j_kind", sa.String(length=12), server_default="professional", nullable=False),
        sa.Column("account_name", sa.String(length=140), nullable=False),
        sa.Column("bank_account", sa.String(length=20), nullable=False),
        sa.Column("ifsc", sa.String(length=11), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending_verification", nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending_verification', 'verified')", name=op.f("ck_vendor_payment_profiles_status")),
        sa.CheckConstraint("tds_section IS NULL OR tds_section IN ('194C', '194J', '194Q')",
                           name=op.f("ck_vendor_payment_profiles_tds_section")),
        sa.CheckConstraint("payee_type IN ('individual', 'company', 'other')", name=op.f("ck_vendor_payment_profiles_payee_type")),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name=op.f("fk_vendor_payment_profiles_vendor_id_vendors")),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], name=op.f("fk_vendor_payment_profiles_changed_by_users")),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], name=op.f("fk_vendor_payment_profiles_verified_by_users")),
        sa.UniqueConstraint("org_id", "vendor_id", name=op.f("uq_vendor_payment_profiles_org_id")),
    )
    op.create_index(op.f("ix_vendor_payment_profiles_org_id"), "vendor_payment_profiles", ["org_id"])

    op.create_table(
        "payment_runs", *_common("payment_runs"),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("prepared_by", sa.UUID(), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_reason", sa.Text(), nullable=True),
        sa.Column("total_gross", MONEY, server_default="0", nullable=False),
        sa.Column("total_tds", MONEY, server_default="0", nullable=False),
        sa.Column("total_net", MONEY, server_default="0", nullable=False),
        sa.Column("bank_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'sent', 'settled', 'partly_failed', 'cancelled')",
                           name=op.f("ck_payment_runs_status")),
        sa.ForeignKeyConstraint(["prepared_by"], ["users.id"], name=op.f("fk_payment_runs_prepared_by_users")),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name=op.f("fk_payment_runs_approved_by_users")),
        sa.UniqueConstraint("org_id", "number", name=op.f("uq_payment_runs_org_id")),
    )
    op.create_index(op.f("ix_payment_runs_org_id"), "payment_runs", ["org_id"])

    op.create_table(
        "payment_lines", *_common("payment_lines"),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("gross", MONEY, nullable=False),
        sa.Column("tds_base", MONEY, server_default="0", nullable=False),
        sa.Column("tds_section", sa.String(length=4), nullable=True),
        sa.Column("tds_rate", sa.Numeric(7, 4), server_default="0", nullable=False),
        sa.Column("tds_amount", MONEY, server_default="0", nullable=False),
        sa.Column("net", MONEY, nullable=False),
        sa.Column("risk_results", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("risk_rule_set_version", sa.String(length=20), nullable=False),
        sa.Column("tds_rule_set_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("utr", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'paid', 'failed', 'removed')", name=op.f("ck_payment_lines_status")),
        sa.ForeignKeyConstraint(["run_id"], ["payment_runs.id"], name=op.f("fk_payment_lines_run_id_payment_runs")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_payment_lines_invoice_id_invoices")),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name=op.f("fk_payment_lines_vendor_id_vendors")),
    )
    op.create_index(op.f("ix_payment_lines_org_id"), "payment_lines", ["org_id"])
    op.create_index(op.f("ix_payment_lines_run_id"), "payment_lines", ["run_id"])
    op.create_index(op.f("ix_payment_lines_invoice_id"), "payment_lines", ["invoice_id"])
    op.create_index("uq_payment_lines_utr", "payment_lines", ["utr"], unique=True, postgresql_where=sa.text("utr IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("payment_lines")
    op.drop_table("payment_runs")
    op.drop_table("vendor_payment_profiles")
