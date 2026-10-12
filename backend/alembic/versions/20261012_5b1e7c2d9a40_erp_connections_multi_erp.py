"""Step 12 (BUILD_PLAN v2.2 §5, ADR 0004/0006): erp_connections + erp_connection_id on mirrored rows.

Additive in effect: a new table and new columns; nothing is deleted. Each org gets one active
"ERPNext · simulated" connection and every existing mirrored row is pointed at it, so all current
data stays visible. The mirror's uniqueness widens from (org_id, erp_ref) to
(org_id, erp_connection_id, erp_ref), because two ERPs may reuse the same document number.
The restricted app role gets its grants through the default privileges set in the first migration.

Revision ID: 5b1e7c2d9a40
Revises: 0126c4a935a7
Create Date: 2026-10-12 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b1e7c2d9a40"
down_revision: str | None = "0126c4a935a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIRRORED = ("vendors", "purchase_orders", "po_lines", "goods_receipts", "grn_lines")


def upgrade() -> None:
    op.create_table(
        "erp_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("system", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="not_connected", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check", postgresql.JSONB(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("mode IN ('simulated', 'live')", name=op.f("ck_erp_connections_mode")),
        sa.CheckConstraint("status IN ('not_connected', 'connected', 'error')", name=op.f("ck_erp_connections_status")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_erp_connections_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_connections")),
        sa.UniqueConstraint("org_id", "system", "mode", name=op.f("uq_erp_connections_org_id")),
    )
    op.create_index(op.f("ix_erp_connections_org_id"), "erp_connections", ["org_id"])
    op.create_index("uq_erp_connections_one_active", "erp_connections", ["org_id"], unique=True,
                    postgresql_where=sa.text("is_active"))

    # One active simulated ERPNext connection per existing org (what the app used until now).
    op.execute("""
        INSERT INTO erp_connections (id, org_id, system, mode, is_active, status)
        SELECT gen_random_uuid(), id, 'erpnext', 'simulated', true, 'connected' FROM orgs
    """)

    for table in (*MIRRORED, "erp_outbox"):
        op.add_column(table, sa.Column("erp_connection_id", sa.UUID(), nullable=True))
        op.execute(f"""
            UPDATE {table} t SET erp_connection_id = c.id
            FROM erp_connections c WHERE c.org_id = t.org_id AND c.is_active
        """)
        op.alter_column(table, "erp_connection_id", nullable=False)
        op.create_foreign_key(op.f(f"fk_{table}_erp_connection_id_erp_connections"), table, "erp_connections",
                              ["erp_connection_id"], ["id"])
        op.create_index(op.f(f"ix_{table}_erp_connection_id"), table, ["erp_connection_id"])

    for table in MIRRORED:
        op.drop_constraint(f"uq_{table}_org_id", table, type_="unique")
        op.create_unique_constraint(f"uq_{table}_org_id", table, ["org_id", "erp_connection_id", "erp_ref"])

    op.add_column("purchase_orders", sa.Column("po_number", sa.String(length=140), nullable=True))
    op.create_index(op.f("ix_purchase_orders_po_number"), "purchase_orders", ["po_number"])


def downgrade() -> None:
    op.drop_index(op.f("ix_purchase_orders_po_number"), table_name="purchase_orders")
    op.drop_column("purchase_orders", "po_number")
    for table in MIRRORED:
        op.drop_constraint(f"uq_{table}_org_id", table, type_="unique")
        op.create_unique_constraint(f"uq_{table}_org_id", table, ["org_id", "erp_ref"])
    for table in (*MIRRORED, "erp_outbox"):
        op.drop_index(op.f(f"ix_{table}_erp_connection_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_erp_connection_id_erp_connections"), table, type_="foreignkey")
        op.drop_column(table, "erp_connection_id")
    op.drop_index("uq_erp_connections_one_active", table_name="erp_connections")
    op.drop_index(op.f("ix_erp_connections_org_id"), table_name="erp_connections")
    op.drop_table("erp_connections")
