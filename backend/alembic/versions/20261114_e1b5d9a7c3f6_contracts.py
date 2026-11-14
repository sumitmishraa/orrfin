"""Step 33 (BUILD_PLAN v3.0 change 44, §5): contracts, their key terms with evidence, obligations.

Additive only. One contract keeps its latest signed file in `document_id`; earlier files stay in
`documents` and in the audit trail.

Revision ID: e1b5d9a7c3f6
Revises: d0a4c8f6b2e5
Create Date: 2026-11-14 19:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1b5d9a7c3f6"
down_revision: str | None = "d0a4c8f6b2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f(f"fk_{table}_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"))


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=True),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("activated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'active', 'expired', 'terminated')", name=op.f("ck_contracts_status")),
        _fk("contracts", "supplier_id", "suppliers"), _fk("contracts", "vendor_id", "vendors"),
        _fk("contracts", "owner_id", "users"), _fk("contracts", "document_id", "documents"),
        _fk("contracts", "activated_by", "users"),
        *_base("contracts"),
    )
    op.create_index(op.f("ix_contracts_org_id"), "contracts", ["org_id"])
    op.create_table(
        "contract_terms",
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(length=5), nullable=False),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("source IN ('ai', 'human')", name=op.f("ck_contract_terms_source")),
        sa.UniqueConstraint("contract_id", "field", name=op.f("uq_contract_terms_contract_id")),
        _fk("contract_terms", "contract_id", "contracts"), _fk("contract_terms", "confirmed_by", "users"),
        *_base("contract_terms"),
    )
    op.create_index(op.f("ix_contract_terms_org_id"), "contract_terms", ["org_id"])
    op.create_index(op.f("ix_contract_terms_contract_id"), "contract_terms", ["contract_id"])
    op.create_table(
        "contract_obligations",
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=5), server_default="open", nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="manual", nullable=False),
        sa.CheckConstraint("status IN ('open', 'done')", name=op.f("ck_contract_obligations_status")),
        _fk("contract_obligations", "contract_id", "contracts"), _fk("contract_obligations", "owner_id", "users"),
        *_base("contract_obligations"),
    )
    op.create_index(op.f("ix_contract_obligations_org_id"), "contract_obligations", ["org_id"])
    op.create_index(op.f("ix_contract_obligations_contract_id"), "contract_obligations", ["contract_id"])


def downgrade() -> None:
    for table in ("contract_obligations", "contract_terms", "contracts"):
        op.drop_table(table)
