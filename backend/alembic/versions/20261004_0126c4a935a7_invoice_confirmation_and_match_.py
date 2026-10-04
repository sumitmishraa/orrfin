"""Steps 7-8 (additive only, demo-week rule §10 F): invoice confirmation + manual-entry reason;
match risk score and plain-English explanation.
Revision ID: 0126c4a935a7
Revises: 02f02c162b9c
Create Date: 2026-10-04 10:44:01.807500
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0126c4a935a7'
down_revision: str | None = '02f02c162b9c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('vendor_name', sa.String(length=200), nullable=True))
    op.add_column('invoices', sa.Column('buyer_gstin', sa.String(length=15), nullable=True))
    op.add_column('invoices', sa.Column('po_reference', sa.String(length=140), nullable=True))
    op.add_column('invoices', sa.Column('place_of_supply', sa.String(length=2), nullable=True))
    op.add_column('invoices', sa.Column('extraction_error', sa.Text(), nullable=True))
    op.add_column('invoices', sa.Column('confirmed_by', sa.UUID(), nullable=True))
    op.add_column('invoices', sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f('fk_invoices_confirmed_by_users'), 'invoices', 'users', ['confirmed_by'], ['id'])
    op.add_column('match_results', sa.Column('risk_score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('match_results', sa.Column('explanation', sa.Text(), nullable=True))
    op.add_column('match_results', sa.Column('explanation_source', sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column('match_results', 'explanation_source')
    op.drop_column('match_results', 'explanation')
    op.drop_column('match_results', 'risk_score')
    op.drop_constraint(op.f('fk_invoices_confirmed_by_users'), 'invoices', type_='foreignkey')
    op.drop_column('invoices', 'confirmed_at')
    op.drop_column('invoices', 'confirmed_by')
    op.drop_column('invoices', 'extraction_error')
    op.drop_column('invoices', 'place_of_supply')
    op.drop_column('invoices', 'po_reference')
    op.drop_column('invoices', 'buyer_gstin')
    op.drop_column('invoices', 'vendor_name')
