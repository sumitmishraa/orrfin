"""Step 37 (BUILD_PLAN v3.0 change 49): App Studio objects and their records.

Additive only. An object is data (fields, approver role, list columns), never code.

Revision ID: b4e8c0d6f2a9
Revises: a3d7b9c5e1f8
Create Date: 2026-11-15 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e8c0d6f2a9"
down_revision: str | None = "a3d7b9c5e1f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list:
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
        "app_objects",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("approver_role", sa.String(length=10), nullable=False),
        sa.Column("list_columns", postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_app_objects_created_by_users")),
        sa.UniqueConstraint("org_id", "key", name=op.f("uq_app_objects_org_id")),
        *_base("app_objects"),
    )
    op.create_index(op.f("ix_app_objects_org_id"), "app_objects", ["org_id"])
    op.create_table(
        "app_records",
        sa.Column("object_id", sa.UUID(), nullable=False),
        sa.Column("values", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('submitted', 'approved', 'rejected')", name=op.f("ck_app_records_status")),
        sa.ForeignKeyConstraint(["object_id"], ["app_objects.id"], name=op.f("fk_app_records_object_id_app_objects")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_app_records_created_by_users")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_app_records_decided_by_users")),
        *_base("app_records"),
    )
    op.create_index(op.f("ix_app_records_org_id"), "app_records", ["org_id"])
    op.create_index(op.f("ix_app_records_object_id"), "app_records", ["object_id"])


def downgrade() -> None:
    op.drop_table("app_records")
    op.drop_table("app_objects")
