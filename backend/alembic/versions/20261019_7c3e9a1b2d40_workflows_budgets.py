"""Step 22 (BUILD_PLAN v2.4 changes 29–30): workflows and budgets.

Additive only: three new tables and five new nullable columns; nothing changes or disappears.
- org_settings: per-org workflow settings (the approval SLA behind "overdue" and reminders).
- exception_tasks: a reviewer holds an invoice and asks someone a question (Zip's exception task).
- budgets: one amount per cost centre per financial-year quarter (warnings only, never blocks).
- categories.extra_approver_id / extra_step_label: an extra named approval step for a category.
- request_approvals.designated_approver_id / step_label: that step, copied into the chain when it
  starts, so a later category change never alters a chain already running.
The app role gets its grants through the default privileges set in the first migration.

Revision ID: 7c3e9a1b2d40
Revises: 5b1e7c2d9a40
Create Date: 2026-10-19 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c3e9a1b2d40"
down_revision: str | None = "5b1e7c2d9a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "org_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("approval_sla_hours", sa.Integer(), server_default="48", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("approval_sla_hours BETWEEN 1 AND 720", name=op.f("ck_org_settings_sla")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_org_settings_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_settings")),
        sa.UniqueConstraint("org_id", name=op.f("uq_org_settings_org_id")),
    )

    op.create_table(
        "exception_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("asked_by", sa.UUID(), nullable=False),
        sa.Column("assigned_to", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open', 'answered', 'closed')", name=op.f("ck_exception_tasks_status")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_exception_tasks_org_id_orgs")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_exception_tasks_invoice_id_invoices")),
        sa.ForeignKeyConstraint(["asked_by"], ["users.id"], name=op.f("fk_exception_tasks_asked_by_users")),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], name=op.f("fk_exception_tasks_assigned_to_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exception_tasks")),
    )
    op.create_index(op.f("ix_exception_tasks_org_id"), "exception_tasks", ["org_id"])
    op.create_index(op.f("ix_exception_tasks_invoice_id"), "exception_tasks", ["invoice_id"])
    op.create_index(op.f("ix_exception_tasks_assigned_to"), "exception_tasks", ["assigned_to"])

    op.create_table(
        "budgets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("cost_center", sa.String(length=60), nullable=False),
        sa.Column("fiscal_year", sa.String(length=9), nullable=False),
        sa.Column("quarter", sa.SmallInteger(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("quarter BETWEEN 1 AND 4", name=op.f("ck_budgets_quarter")),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_budgets_amount")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_budgets_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint("org_id", "cost_center", "fiscal_year", "quarter", name=op.f("uq_budgets_org_id")),
    )
    op.create_index(op.f("ix_budgets_org_id"), "budgets", ["org_id"])

    op.add_column("categories", sa.Column("extra_approver_id", sa.UUID(), nullable=True))
    op.add_column("categories", sa.Column("extra_step_label", sa.String(length=80), nullable=True))
    op.create_foreign_key(op.f("fk_categories_extra_approver_id_users"), "categories", "users",
                          ["extra_approver_id"], ["id"])
    op.add_column("request_approvals", sa.Column("designated_approver_id", sa.UUID(), nullable=True))
    op.add_column("request_approvals", sa.Column("step_label", sa.String(length=80), nullable=True))
    op.create_foreign_key(op.f("fk_request_approvals_designated_approver_id_users"), "request_approvals", "users",
                          ["designated_approver_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(op.f("fk_request_approvals_designated_approver_id_users"), "request_approvals",
                       type_="foreignkey")
    op.drop_column("request_approvals", "step_label")
    op.drop_column("request_approvals", "designated_approver_id")
    op.drop_constraint(op.f("fk_categories_extra_approver_id_users"), "categories", type_="foreignkey")
    op.drop_column("categories", "extra_step_label")
    op.drop_column("categories", "extra_approver_id")
    op.drop_table("budgets")
    op.drop_table("exception_tasks")
    op.drop_table("org_settings")
