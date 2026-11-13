"""Step 31 (BUILD_PLAN v3.0 change 50, §9 "Stronger sign-in"): login_throttles, the lockout counter.

Additive only. One row per email that has had a wrong password recently (only a SHA-256 of the
email is kept). It has no org_id on purpose: it is written before anyone is logged in, and for
emails that may not belong to any account.

Revision ID: d1a4c8e2f7b9
Revises: c7a2e9f1b3d5
Create Date: 2026-11-13 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a4c8e2f7b9"
down_revision: str | None = "c7a2e9f1b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_throttles")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_login_throttles_key_hash")),
    )


def downgrade() -> None:
    op.drop_table("login_throttles")
