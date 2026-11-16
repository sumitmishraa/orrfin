"""Step 41 (ADR 0011): team invitations, the simulated power-seat plan, and member details.

Additive only. `team_invites` holds single-use invitation links (only a SHA-256 of the token is kept,
7-day expiry, §9). It is left out of row-level security like `users` and `supplier_invites`, because
accepting an invitation looks the token up before anyone is signed in; the service filters by org.

Revision ID: d6a0e2f8b4c1
Revises: c5f9d1e7a3b0
Create Date: 2026-11-16 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6a0e2f8b4c1"
down_revision: str | None = "c5f9d1e7a3b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("requester", "buyer", "approver", "finance", "admin")


def upgrade() -> None:
    op.add_column("orgs", sa.Column("plan_name", sa.String(length=40), server_default="Growth", nullable=False))
    op.add_column("orgs", sa.Column("power_seat_limit", sa.Integer(), server_default="10", nullable=False))
    op.add_column("users", sa.Column("department", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("invited_by_id", sa.UUID(), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f("fk_users_invited_by_id_users"), "users", "users", ["invited_by_id"], ["id"])

    op.create_table(
        "team_invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("approval_limit", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("manager_id", sa.UUID(), nullable=True),
        sa.Column("department", sa.String(length=80), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in ROLES)})", name=op.f("ck_team_invites_role")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_team_invites_org_id_orgs")),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], name=op.f("fk_team_invites_manager_id_users")),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], name=op.f("fk_team_invites_invited_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_team_invites_token_hash")),
    )
    op.create_index(op.f("ix_team_invites_org_id"), "team_invites", ["org_id"])
    op.create_index(op.f("ix_team_invites_email"), "team_invites", ["email"])


def downgrade() -> None:
    op.drop_index(op.f("ix_team_invites_email"), table_name="team_invites")
    op.drop_index(op.f("ix_team_invites_org_id"), table_name="team_invites")
    op.drop_table("team_invites")
    op.drop_constraint(op.f("fk_users_invited_by_id_users"), "users", type_="foreignkey")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "invited_by_id")
    op.drop_column("users", "department")
    op.drop_column("orgs", "power_seat_limit")
    op.drop_column("orgs", "plan_name")
