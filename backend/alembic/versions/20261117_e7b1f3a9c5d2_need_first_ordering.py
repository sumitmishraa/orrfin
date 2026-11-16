"""Step 42 (ADR 0012): need-first intake, combined POs built by procurement, and messages to vendors.

Additive. New columns: orgs.intake_flow, purchase_requests.source_channel / source_message /
entered_by_id, request_lines.unit, purchase_orders.order_po_id and erp_outbox.order_po_id. New tables:
order_pos, order_po_lines, order_po_line_sources, order_po_approvals and vendor_messages, each with
org_id and the same row-level-security policy as every other business table (Step 38). The app role
gets access through the default privileges set in the first migration.

The outbox check `one_source` is widened, not narrowed: a row still has exactly one source document,
which may now also be an order PO. Every existing row already satisfies the new check.

Revision ID: e7b1f3a9c5d2
Revises: d6a0e2f8b4c1
Create Date: 2026-11-17 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b1f3a9c5d2"
down_revision: str | None = "d6a0e2f8b4c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER_PO_STATUSES = ("draft", "in_approval", "returned", "approved", "rejected", "sent", "cancelled")
NEW_TABLES = ("order_pos", "order_po_lines", "order_po_line_sources", "order_po_approvals", "vendor_messages")
POLICY = ("(nullif(current_setting('app.org_id', true), '') IS NULL "
          "OR org_id = nullif(current_setting('app.org_id', true), '')::uuid)")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _stamps() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.add_column("orgs", sa.Column("intake_flow", sa.String(length=20), server_default="buyer_first", nullable=False))
    op.create_check_constraint(op.f("ck_orgs_intake_flow"), "orgs", _in("intake_flow", ("buyer_first", "need_first")))
    op.add_column("purchase_requests",
                  sa.Column("source_channel", sa.String(length=10), server_default="form", nullable=False))
    op.create_check_constraint(op.f("ck_purchase_requests_source_channel"), "purchase_requests",
                               _in("source_channel", ("form", "whatsapp", "email")))
    op.add_column("purchase_requests", sa.Column("source_message", sa.Text(), nullable=True))
    op.add_column("purchase_requests", sa.Column("entered_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_purchase_requests_entered_by_id_users"), "purchase_requests", "users",
                          ["entered_by_id"], ["id"])
    op.add_column("request_lines", sa.Column("unit", sa.String(length=20), nullable=True))

    op.create_table(
        "order_pos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("needed_by", sa.Date(), nullable=True),
        sa.Column("note_to_vendor", sa.Text(), server_default="", nullable=False),
        sa.Column("approval_round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_by_id", sa.UUID(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_by_id", sa.UUID(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(_in("status", ORDER_PO_STATUSES), name=op.f("ck_order_pos_status")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_order_pos_org_id_orgs")),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name=op.f("fk_order_pos_vendor_id_vendors")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_order_pos_created_by_id_users")),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], name=op.f("fk_order_pos_completed_by_id_users")),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], name=op.f("fk_order_pos_sent_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_pos")),
        sa.UniqueConstraint("org_id", "number", name=op.f("uq_order_pos_org_id")),
    )
    op.create_index(op.f("ix_order_pos_org_id"), "order_pos", ["org_id"])

    op.create_table(
        "order_po_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("order_po_id", sa.UUID(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.String(length=140), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("hsn", sa.String(length=10), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_order_po_lines_org_id_orgs")),
        sa.ForeignKeyConstraint(["order_po_id"], ["order_pos.id"], ondelete="CASCADE",
                                name=op.f("fk_order_po_lines_order_po_id_order_pos")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_po_lines")),
    )
    op.create_index(op.f("ix_order_po_lines_org_id"), "order_po_lines", ["org_id"])
    op.create_index(op.f("ix_order_po_lines_order_po_id"), "order_po_lines", ["order_po_id"])

    op.create_table(
        "order_po_line_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("order_po_line_id", sa.UUID(), nullable=False),
        sa.Column("request_line_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_order_po_line_sources_org_id_orgs")),
        sa.ForeignKeyConstraint(["order_po_line_id"], ["order_po_lines.id"], ondelete="CASCADE",
                                name=op.f("fk_order_po_line_sources_order_po_line_id_order_po_lines")),
        sa.ForeignKeyConstraint(["request_line_id"], ["request_lines.id"],
                                name=op.f("fk_order_po_line_sources_request_line_id_request_lines")),
        sa.ForeignKeyConstraint(["request_id"], ["purchase_requests.id"],
                                name=op.f("fk_order_po_line_sources_request_id_purchase_requests")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_po_line_sources")),
    )
    op.create_index(op.f("ix_order_po_line_sources_org_id"), "order_po_line_sources", ["org_id"])
    op.create_index(op.f("ix_order_po_line_sources_order_po_line_id"), "order_po_line_sources", ["order_po_line_id"])
    op.create_index(op.f("ix_order_po_line_sources_request_line_id"), "order_po_line_sources", ["request_line_id"])
    op.create_index(op.f("ix_order_po_line_sources_request_id"), "order_po_line_sources", ["request_id"])
    # One live PO per request line: the database refuses a second, even if two buyers click at once.
    op.create_index("uq_order_po_line_sources_live_request_line", "order_po_line_sources", ["request_line_id"],
                    unique=True, postgresql_where=sa.text("active"))

    op.create_table(
        "order_po_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("order_po_id", sa.UUID(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("required_role", sa.String(length=20), nullable=False),
        sa.Column("approver_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(_in("decision", ("approve", "reject", "return")),
                           name=op.f("ck_order_po_approvals_decision")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_order_po_approvals_org_id_orgs")),
        sa.ForeignKeyConstraint(["order_po_id"], ["order_pos.id"],
                                name=op.f("fk_order_po_approvals_order_po_id_order_pos")),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], name=op.f("fk_order_po_approvals_approver_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_po_approvals")),
        sa.UniqueConstraint("order_po_id", "round", "step", name=op.f("uq_order_po_approvals_order_po_id")),
    )
    op.create_index(op.f("ix_order_po_approvals_org_id"), "order_po_approvals", ["org_id"])
    op.create_index(op.f("ix_order_po_approvals_order_po_id"), "order_po_approvals", ["order_po_id"])

    op.create_table(
        "vendor_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("order_po_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=300), server_default="", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachment_name", sa.String(length=200), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        *_stamps(),
        sa.CheckConstraint(_in("channel", ("email", "whatsapp")), name=op.f("ck_vendor_messages_channel")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_vendor_messages_org_id_orgs")),
        sa.ForeignKeyConstraint(["order_po_id"], ["order_pos.id"], name=op.f("fk_vendor_messages_order_po_id_order_pos")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_vendor_messages_created_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_messages")),
    )
    op.create_index(op.f("ix_vendor_messages_org_id"), "vendor_messages", ["org_id"])
    op.create_index(op.f("ix_vendor_messages_order_po_id"), "vendor_messages", ["order_po_id"])

    op.add_column("purchase_orders", sa.Column("order_po_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_purchase_orders_order_po_id_order_pos"), "purchase_orders", "order_pos",
                          ["order_po_id"], ["id"])
    op.add_column("erp_outbox", sa.Column("order_po_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_erp_outbox_order_po_id_order_pos"), "erp_outbox", "order_pos",
                          ["order_po_id"], ["id"])
    op.drop_constraint(op.f("ck_erp_outbox_one_source"), "erp_outbox", type_="check")
    op.create_check_constraint(op.f("ck_erp_outbox_one_source"), "erp_outbox",
                               "num_nonnulls(invoice_id, request_id, order_po_id) = 1")

    for table in NEW_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY org_isolation ON "{table}" USING {POLICY} WITH CHECK {POLICY}')


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(f'DROP POLICY IF EXISTS org_isolation ON "{table}"')
    op.drop_constraint(op.f("ck_erp_outbox_one_source"), "erp_outbox", type_="check")
    op.create_check_constraint(op.f("ck_erp_outbox_one_source"), "erp_outbox",
                               "(invoice_id IS NULL) <> (request_id IS NULL)")
    op.drop_constraint(op.f("fk_erp_outbox_order_po_id_order_pos"), "erp_outbox", type_="foreignkey")
    op.drop_column("erp_outbox", "order_po_id")
    op.drop_constraint(op.f("fk_purchase_orders_order_po_id_order_pos"), "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "order_po_id")
    op.drop_table("vendor_messages")
    op.drop_table("order_po_approvals")
    op.drop_index("uq_order_po_line_sources_live_request_line", table_name="order_po_line_sources")
    op.drop_table("order_po_line_sources")
    op.drop_table("order_po_lines")
    op.drop_table("order_pos")
    op.drop_column("request_lines", "unit")
    op.drop_constraint(op.f("fk_purchase_requests_entered_by_id_users"), "purchase_requests", type_="foreignkey")
    op.drop_column("purchase_requests", "entered_by_id")
    op.drop_column("purchase_requests", "source_message")
    op.drop_constraint(op.f("ck_purchase_requests_source_channel"), "purchase_requests", type_="check")
    op.drop_column("purchase_requests", "source_channel")
    op.drop_constraint(op.f("ck_orgs_intake_flow"), "orgs", type_="check")
    op.drop_column("orgs", "intake_flow")
