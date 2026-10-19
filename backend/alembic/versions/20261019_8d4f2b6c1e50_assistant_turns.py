"""Step 23 (BUILD_PLAN v2.3 change 25, §5): assistant_turns, a log of every assistant question and answer.

Additive only. Not an audit event: asking changes nothing. It records what was asked, which
read-only tools ran with which arguments (not their results), the answer, the model and prompt
version, and whether every ₹ figure in the answer was found in the tool results.

Revision ID: 8d4f2b6c1e50
Revises: 7c3e9a1b2d40
Create Date: 2026-10-19 14:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d4f2b6c1e50"
down_revision: str | None = "7c3e9a1b2d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_assistant_turns_org_id_orgs")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_assistant_turns_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_turns")),
    )
    op.create_index(op.f("ix_assistant_turns_org_id"), "assistant_turns", ["org_id"])
    op.create_index("ix_assistant_turns_user_created", "assistant_turns", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("assistant_turns")
