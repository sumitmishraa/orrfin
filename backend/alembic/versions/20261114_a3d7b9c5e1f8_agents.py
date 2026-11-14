"""Step 35 (BUILD_PLAN v3.0 change 47, ADR 0007): AI proposals and the agent run log.

Additive only. A proposal is what an AI suggested, frozen with its SHA-256: a person submits it
through the normal endpoint, once, before it expires. The run log records which agent ran,
over which channel (chat or MCP), which tools it used and which proposals it made.

Revision ID: a3d7b9c5e1f8
Revises: f2c6a8b4d0e7
Create Date: 2026-11-14 23:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3d7b9c5e1f8"
down_revision: str | None = "f2c6a8b4d0e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f(f"fk_{table}_org_id_orgs")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("kind IN ('request', 'supplier_invite', 'workflow_draft', 'rfq')",
                           name=op.f("ck_action_proposals_kind")),
        *_base("action_proposals"),
    )
    op.create_index(op.f("ix_action_proposals_org_id"), "action_proposals", ["org_id"])
    op.create_table(
        "agent_runs",
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=5), nullable=False),
        sa.Column("tools_used", postgresql.JSONB(), nullable=False),
        sa.Column("proposal_ids", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.CheckConstraint("channel IN ('chat', 'mcp')", name=op.f("ck_agent_runs_channel")),
        *_base("agent_runs"),
    )
    op.create_index(op.f("ix_agent_runs_org_id"), "agent_runs", ["org_id"])
    op.create_index(op.f("ix_agent_runs_user_id"), "agent_runs", ["user_id"])


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("action_proposals")
