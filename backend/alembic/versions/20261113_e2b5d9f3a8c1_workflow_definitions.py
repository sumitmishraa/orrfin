"""Step 31 (BUILD_PLAN v3.0 change 39, §5, ADR 0010): workflow_definitions and workflow_versions.

Additive only. A definition is a named workflow of an org; each version holds one saved set of
steps as JSON with its SHA-256. A published version is never edited (the service refuses it).

Revision ID: e2b5d9f3a8c1
Revises: d1a4c8e2f7b9
Create Date: 2026-11-13 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2b5d9f3a8c1"
down_revision: str | None = "d1a4c8e2f7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("active_version_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_workflow_definitions_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_definitions")),
        sa.UniqueConstraint("org_id", "key", name=op.f("uq_workflow_definitions_org_id")),
    )
    op.create_index(op.f("ix_workflow_definitions_org_id"), "workflow_definitions", ["org_id"])

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("definition_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("drafted_by_ai", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('draft', 'published', 'retired')", name=op.f("ck_workflow_versions_status")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_workflow_versions_org_id_orgs")),
        sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"],
                                name=op.f("fk_workflow_versions_definition_id_workflow_definitions")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_workflow_versions_created_by_users")),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"],
                                name=op.f("fk_workflow_versions_published_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_versions")),
        sa.UniqueConstraint("definition_id", "number", name=op.f("uq_workflow_versions_definition_id")),
    )
    op.create_index(op.f("ix_workflow_versions_org_id"), "workflow_versions", ["org_id"])
    op.create_index(op.f("ix_workflow_versions_definition_id"), "workflow_versions", ["definition_id"])


def downgrade() -> None:
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")
