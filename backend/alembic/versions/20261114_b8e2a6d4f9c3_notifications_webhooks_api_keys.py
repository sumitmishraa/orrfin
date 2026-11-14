"""Step 31 (BUILD_PLAN v3.0 §5): in-app notifications, hashed API keys, webhook endpoints and deliveries.

Additive only. An API key is stored as a SHA-256 only; a webhook secret is stored encrypted.

Revision ID: b8e2a6d4f9c3
Revises: a7d1f5c3e8b2
Create Date: 2026-11-14 14:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e2a6d4f9c3"
down_revision: str | None = "a7d1f5c3e8b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list:
    """id, org_id and timestamps, as on every business table (§5)."""
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
        "notifications",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")),
        *_base("notifications"),
    )
    op.create_index(op.f("ix_notifications_org_id"), "notifications", ["org_id"])
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])

    op.create_table(
        "api_keys",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_api_keys_user_id_users")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
        *_base("api_keys"),
    )
    op.create_index(op.f("ix_api_keys_org_id"), "api_keys", ["org_id"])
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"])

    op.create_table(
        "webhook_endpoints",
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_webhook_endpoints_created_by_users")),
        *_base("webhook_endpoints"),
    )
    op.create_index(op.f("ix_webhook_endpoints_org_id"), "webhook_endpoints", ["org_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name=op.f("ck_webhook_deliveries_status")),
        sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"],
                                name=op.f("fk_webhook_deliveries_endpoint_id_webhook_endpoints")),
        *_base("webhook_deliveries"),
    )
    op.create_index(op.f("ix_webhook_deliveries_org_id"), "webhook_deliveries", ["org_id"])
    op.create_index(op.f("ix_webhook_deliveries_endpoint_id"), "webhook_deliveries", ["endpoint_id"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("api_keys")
    op.drop_table("notifications")
