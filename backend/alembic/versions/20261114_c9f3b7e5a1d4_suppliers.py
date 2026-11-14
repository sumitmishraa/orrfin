"""Step 32 (BUILD_PLAN v3.0 changes 41-42, §5, §6e): supplier onboarding, the supplier portal realm, risk.

Additive only. Suppliers log in through their own tables (`supplier_users`, `supplier_sessions`),
never through `users` / `sessions`. A supplier document keeps its own file fields because
`documents.uploaded_by` must be an employee. `sanctions_entries` is a synthetic reference list
shared by all orgs, so it has no org_id.

Revision ID: c9f3b7e5a1d4
Revises: b8e2a6d4f9c3
Create Date: 2026-11-14 16:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9f3b7e5a1d4"
down_revision: str | None = "b8e2a6d4f9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "('invited', 'submitted', 'in_review', 'approved', 'rejected', 'handed_over', 'active')"


def _stamps() -> list:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _base(table: str) -> list:
    """id, org_id and timestamps, as on every business table (§5)."""
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f(f"fk_{table}_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def _supplier_fk(table: str) -> list:
    return [
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f(f"fk_{table}_supplier_id_suppliers")),
    ]


def _indexes(table: str, *columns: str) -> None:
    for column in ("org_id", *columns):
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column("tax_id", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="invited", nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("invited_by", sa.UUID(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("answers", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("bank_details_encrypted", sa.Text(), nullable=True),
        sa.Column("bank_last4", sa.String(length=4), nullable=True),
        sa.Column("bank_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("bank_changed_on", sa.Date(), nullable=True),
        sa.Column("on_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(f"status IN {STATUSES}", name=op.f("ck_suppliers_status")),
        sa.CheckConstraint("country IN ('IN', 'AE')", name=op.f("ck_suppliers_country")),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name=op.f("fk_suppliers_vendor_id_vendors")),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], name=op.f("fk_suppliers_invited_by_users")),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_suppliers_reviewed_by_users")),
        *_base("suppliers"),
    )
    _indexes("suppliers", "bank_fingerprint")

    op.create_table(
        "supplier_users",
        *_supplier_fk("supplier_users"),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_base("supplier_users"),
    )
    _indexes("supplier_users", "supplier_id")
    op.create_index("uq_supplier_users_email_lower", "supplier_users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "supplier_invites",
        *_supplier_fk("supplier_invites"),
        sa.Column("supplier_user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["supplier_user_id"], ["supplier_users.id"],
                                name=op.f("fk_supplier_invites_supplier_user_id_supplier_users")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_supplier_invites_token_hash")),
        *_base("supplier_invites"),
    )
    _indexes("supplier_invites", "supplier_id")

    op.create_table(
        "supplier_sessions",
        sa.Column("supplier_user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["supplier_user_id"], ["supplier_users.id"],
                                name=op.f("fk_supplier_sessions_supplier_user_id_supplier_users")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_supplier_sessions_token_hash")),
        *_base("supplier_sessions"),
    )
    _indexes("supplier_sessions")

    op.create_table(
        "supplier_documents",
        *_supplier_fk("supplier_documents"),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.CheckConstraint("kind IN ('tax_certificate', 'pan', 'bank_proof', 'other')",
                           name=op.f("ck_supplier_documents_kind")),
        *_base("supplier_documents"),
    )
    _indexes("supplier_documents", "supplier_id")

    op.create_table(
        "risk_assessments",
        *_supplier_fk("risk_assessments"),
        sa.Column("rule_set_version", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("next_review_on", sa.Date(), nullable=True),
        sa.CheckConstraint("level IN ('low', 'medium', 'high', 'critical')", name=op.f("ck_risk_assessments_level")),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_risk_assessments_reviewed_by_users")),
        *_base("risk_assessments"),
    )
    _indexes("risk_assessments", "supplier_id")

    op.create_table(
        "sanctions_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("list_name", sa.String(length=80), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sanctions_entries")),
    )
    # Invented names only (synthetic data rule). A real list is loaded at pilot time, after legal review.
    op.execute(
        "INSERT INTO sanctions_entries (id, name, country, list_name) VALUES "
        "(gen_random_uuid(), 'Blocked Exports LLC', 'AE', 'Orrfin synthetic list'), "
        "(gen_random_uuid(), 'Shadow Freight Private Limited', 'IN', 'Orrfin synthetic list'), "
        "(gen_random_uuid(), 'Nightfall Commodities FZE', 'AE', 'Orrfin synthetic list')")


def downgrade() -> None:
    for table in ("sanctions_entries", "risk_assessments", "supplier_documents", "supplier_sessions",
                  "supplier_invites", "supplier_users", "suppliers"):
        op.drop_table(table)
