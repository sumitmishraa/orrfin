"""Step 31 (BUILD_PLAN v3.0 change 40, §5): request types and their form fields.

Additive only. `purchase_requests` gains the type it was raised as and the answers to that type's
extra questions; both are NULL for every existing request, which keeps the plain form.

Revision ID: a7d1f5c3e8b2
Revises: f3c6e0a4b9d2
Create Date: 2026-11-14 11:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d1f5c3e8b2"
down_revision: str | None = "f3c6e0a4b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "request_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("workflow_definition_id", sa.UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_request_types_org_id_orgs")),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"],
                                name=op.f("fk_request_types_workflow_definition_id_workflow_definitions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_types")),
        sa.UniqueConstraint("org_id", "key", name=op.f("uq_request_types_org_id")),
    )
    op.create_index(op.f("ix_request_types_org_id"), "request_types", ["org_id"])

    op.create_table(
        "form_fields",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("request_type_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("options", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('text', 'number', 'money', 'date', 'choice', 'user')",
                           name=op.f("ck_form_fields_kind")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_form_fields_org_id_orgs")),
        sa.ForeignKeyConstraint(["request_type_id"], ["request_types.id"],
                                name=op.f("fk_form_fields_request_type_id_request_types")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_fields")),
        sa.UniqueConstraint("request_type_id", "key", name=op.f("uq_form_fields_request_type_id")),
    )
    op.create_index(op.f("ix_form_fields_org_id"), "form_fields", ["org_id"])
    op.create_index(op.f("ix_form_fields_request_type_id"), "form_fields", ["request_type_id"])

    op.add_column("purchase_requests", sa.Column("request_type_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_purchase_requests_request_type_id_request_types"), "purchase_requests",
                          "request_types", ["request_type_id"], ["id"])
    op.add_column("purchase_requests", sa.Column("custom_values", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_requests", "custom_values")
    op.drop_constraint(op.f("fk_purchase_requests_request_type_id_request_types"), "purchase_requests",
                       type_="foreignkey")
    op.drop_column("purchase_requests", "request_type_id")
    op.drop_table("form_fields")
    op.drop_table("request_types")
