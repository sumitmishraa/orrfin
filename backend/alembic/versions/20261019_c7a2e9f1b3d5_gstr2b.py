"""Step 27 (BUILD_PLAN v2.4 change 34; ADR 0008): GSTR-2B input-tax-credit matching.

Additive only. A GSTR-2B JSON (the GSTN shape) is imported per return period; its b2b lines are matched to
Orrfin's invoices by supplier GSTIN + normalised invoice number + financial year. Matching only: Orrfin
files nothing with GSTN.

Revision ID: c7a2e9f1b3d5
Revises: b6f1d2c3a4e7
Create Date: 2026-10-19 22:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a2e9f1b3d5"
down_revision: str | None = "b6f1d2c3a4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)


def _common(table: str) -> list:
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
        "gstr2b_imports", *_common("gstr2b_imports"),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_gstr2b_imports_uploaded_by_users")),
        sa.UniqueConstraint("org_id", "sha256", name=op.f("uq_gstr2b_imports_org_id")),
    )
    op.create_index(op.f("ix_gstr2b_imports_org_id"), "gstr2b_imports", ["org_id"])
    op.create_table(
        "gstr2b_lines", *_common("gstr2b_lines"),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("supplier_gstin", sa.String(length=15), nullable=False),
        sa.Column("supplier_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("invoice_no", sa.String(length=60), nullable=False),
        sa.Column("invoice_no_norm", sa.String(length=60), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.String(length=9), nullable=False),
        sa.Column("invoice_value", MONEY, nullable=False),
        sa.Column("taxable_value", MONEY, nullable=False),
        sa.Column("igst", MONEY, server_default="0", nullable=False),
        sa.Column("cgst", MONEY, server_default="0", nullable=False),
        sa.Column("sgst", MONEY, server_default="0", nullable=False),
        sa.Column("itc_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("match_status IN ('matched', 'amount_differs', 'not_in_books')",
                           name=op.f("ck_gstr2b_lines_match_status")),
        sa.ForeignKeyConstraint(["import_id"], ["gstr2b_imports.id"], name=op.f("fk_gstr2b_lines_import_id_gstr2b_imports")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_gstr2b_lines_invoice_id_invoices")),
    )
    op.create_index(op.f("ix_gstr2b_lines_org_id"), "gstr2b_lines", ["org_id"])
    op.create_index(op.f("ix_gstr2b_lines_import_id"), "gstr2b_lines", ["import_id"])
    op.create_index("ix_gstr2b_lines_key", "gstr2b_lines", ["org_id", "supplier_gstin", "invoice_no_norm", "fiscal_year"])


def downgrade() -> None:
    op.drop_table("gstr2b_lines")
    op.drop_table("gstr2b_imports")
