"""Schema v2.1: every table in BUILD_PLAN §5, plus sessions, and the app role grants.

Creates the restricted `orrfin_app` role (docs/adr/0002). The app switches to it after
connecting; it may INSERT/SELECT audit_events but never UPDATE/DELETE them (§5 grants).

Revision ID: 02f02c162b9c
Revises: 
Create Date: 2026-09-29 18:15:41.681508
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '02f02c162b9c'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('orgs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orgs'))
    )
    op.create_table('approval_policies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('min_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('max_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_approval_policies_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_policies'))
    )
    op.create_index(op.f('ix_approval_policies_org_id'), 'approval_policies', ['org_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('approval_limit', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('manager_id', sa.UUID(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('requester', 'buyer', 'approver', 'finance', 'admin')", name=op.f('ck_users_role')),
    sa.ForeignKeyConstraint(['manager_id'], ['users.id'], name=op.f('fk_users_manager_id_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_users_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_org_id'), 'users', ['org_id'], unique=False)
    op.create_index('uq_users_email_lower', 'users', [sa.text('lower(email)')], unique=True)
    op.create_table('vendors',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('erp_ref', sa.String(length=140), nullable=False),
    sa.Column('erp_modified', sa.DateTime(timezone=True), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('gstin', sa.String(length=15), nullable=True),
    sa.Column('state_code', sa.String(length=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_vendors_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vendors')),
    sa.UniqueConstraint('org_id', 'erp_ref', name=op.f('uq_vendors_org_id'))
    )
    op.create_index(op.f('ix_vendors_org_id'), 'vendors', ['org_id'], unique=False)
    op.create_table('audit_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_events_actor_id_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_audit_events_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events')),
    sa.UniqueConstraint('entity_id', 'seq', name=op.f('uq_audit_events_entity_id'))
    )
    op.create_index(op.f('ix_audit_events_entity_id'), 'audit_events', ['entity_id'], unique=False)
    op.create_index(op.f('ix_audit_events_org_id'), 'audit_events', ['org_id'], unique=False)
    op.create_table('categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('buyer_id', sa.UUID(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], name=op.f('fk_categories_buyer_id_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_categories_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('org_id', 'name', name=op.f('uq_categories_org_id'))
    )
    op.create_index(op.f('ix_categories_org_id'), 'categories', ['org_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('s3_key', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_documents_org_id_orgs')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_documents_uploaded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('org_id', 'sha256', name=op.f('uq_documents_org_id'))
    )
    op.create_index(op.f('ix_documents_org_id'), 'documents', ['org_id'], unique=False)
    op.create_table('goods_receipts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('erp_ref', sa.String(length=140), nullable=False),
    sa.Column('erp_modified', sa.DateTime(timezone=True), nullable=False),
    sa.Column('vendor_id', sa.UUID(), nullable=True),
    sa.Column('posting_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_goods_receipts_org_id_orgs')),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_goods_receipts_vendor_id_vendors')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_goods_receipts')),
    sa.UniqueConstraint('org_id', 'erp_ref', name=op.f('uq_goods_receipts_org_id'))
    )
    op.create_index(op.f('ix_goods_receipts_org_id'), 'goods_receipts', ['org_id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.String(length=10), server_default='queued', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f('ck_jobs_status')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_jobs_created_by_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_jobs_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_index(op.f('ix_jobs_org_id'), 'jobs', ['org_id'], unique=False)
    op.create_index('ix_jobs_status_run_after', 'jobs', ['status', 'run_after'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_sessions_org_id_orgs')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index(op.f('ix_sessions_org_id'), 'sessions', ['org_id'], unique=False)
    op.create_table('purchase_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('justification', sa.Text(), server_default='', nullable=False),
    sa.Column('cost_center', sa.String(length=60), server_default='', nullable=False),
    sa.Column('needed_by', sa.Date(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
    sa.Column('assigned_buyer_id', sa.UUID(), nullable=True),
    sa.Column('suggested_vendor_id', sa.UUID(), nullable=True),
    sa.Column('vendor_id', sa.UUID(), nullable=True),
    sa.Column('completed_by_id', sa.UUID(), nullable=True),
    sa.Column('approval_round', sa.Integer(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'submitted', 'with_buyer', 'in_approval', 'returned', 'approved', 'rejected', 'po_drafted', 'po_open', 'cancelled')", name=op.f('ck_purchase_requests_status')),
    sa.ForeignKeyConstraint(['assigned_buyer_id'], ['users.id'], name=op.f('fk_purchase_requests_assigned_buyer_id_users')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_purchase_requests_category_id_categories')),
    sa.ForeignKeyConstraint(['completed_by_id'], ['users.id'], name=op.f('fk_purchase_requests_completed_by_id_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_purchase_requests_org_id_orgs')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_purchase_requests_requested_by_users')),
    sa.ForeignKeyConstraint(['suggested_vendor_id'], ['vendors.id'], name=op.f('fk_purchase_requests_suggested_vendor_id_vendors')),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_purchase_requests_vendor_id_vendors')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_purchase_requests')),
    sa.UniqueConstraint('org_id', 'number', name=op.f('uq_purchase_requests_org_id'))
    )
    op.create_index(op.f('ix_purchase_requests_org_id'), 'purchase_requests', ['org_id'], unique=False)
    op.create_table('purchase_orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('erp_ref', sa.String(length=140), nullable=False),
    sa.Column('erp_modified', sa.DateTime(timezone=True), nullable=False),
    sa.Column('vendor_id', sa.UUID(), nullable=True),
    sa.Column('po_date', sa.Date(), nullable=True),
    sa.Column('schedule_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
    sa.Column('net_total', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('tax_total', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('grand_total', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=True),
    sa.Column('origin', sa.String(length=10), server_default='erp', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('orrfin', 'erp')", name=op.f('ck_purchase_orders_origin')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_purchase_orders_org_id_orgs')),
    sa.ForeignKeyConstraint(['request_id'], ['purchase_requests.id'], name=op.f('fk_purchase_orders_request_id_purchase_requests')),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_purchase_orders_vendor_id_vendors')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_purchase_orders')),
    sa.UniqueConstraint('org_id', 'erp_ref', name=op.f('uq_purchase_orders_org_id'))
    )
    op.create_index(op.f('ix_purchase_orders_org_id'), 'purchase_orders', ['org_id'], unique=False)
    op.create_table('request_approvals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('step', sa.Integer(), nullable=False),
    sa.Column('required_role', sa.String(length=20), nullable=False),
    sa.Column('approver_id', sa.UUID(), nullable=True),
    sa.Column('decision', sa.String(length=10), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('approve', 'reject', 'return')", name=op.f('ck_request_approvals_decision')),
    sa.ForeignKeyConstraint(['approver_id'], ['users.id'], name=op.f('fk_request_approvals_approver_id_users')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_request_approvals_org_id_orgs')),
    sa.ForeignKeyConstraint(['request_id'], ['purchase_requests.id'], name=op.f('fk_request_approvals_request_id_purchase_requests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_approvals')),
    sa.UniqueConstraint('request_id', 'round', 'step', name=op.f('uq_request_approvals_request_id'))
    )
    op.create_index(op.f('ix_request_approvals_org_id'), 'request_approvals', ['org_id'], unique=False)
    op.create_index(op.f('ix_request_approvals_request_id'), 'request_approvals', ['request_id'], unique=False)
    op.create_table('request_lines',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('item_code', sa.String(length=140), nullable=True),
    sa.Column('qty', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('est_rate', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('hsn', sa.String(length=10), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_request_lines_org_id_orgs')),
    sa.ForeignKeyConstraint(['request_id'], ['purchase_requests.id'], name=op.f('fk_request_lines_request_id_purchase_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_lines'))
    )
    op.create_index(op.f('ix_request_lines_org_id'), 'request_lines', ['org_id'], unique=False)
    op.create_index(op.f('ix_request_lines_request_id'), 'request_lines', ['request_id'], unique=False)
    op.create_table('invoices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('vendor_id', sa.UUID(), nullable=True),
    sa.Column('po_id', sa.UUID(), nullable=True),
    sa.Column('vendor_gstin', sa.String(length=15), nullable=True),
    sa.Column('invoice_no', sa.String(length=60), nullable=True),
    sa.Column('invoice_no_norm', sa.String(length=60), nullable=True),
    sa.Column('invoice_date', sa.Date(), nullable=True),
    sa.Column('fiscal_year', sa.String(length=9), nullable=True),
    sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cgst', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('sgst', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('igst', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('total', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('status', sa.String(length=30), server_default='uploaded', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_invoices_document_id_documents')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_invoices_org_id_orgs')),
    sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id'], name=op.f('fk_invoices_po_id_purchase_orders')),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], name=op.f('fk_invoices_vendor_id_vendors')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices'))
    )
    op.create_index('ix_invoices_duplicate_key', 'invoices', ['org_id', 'vendor_gstin', 'invoice_no_norm', 'fiscal_year'], unique=False)
    op.create_index(op.f('ix_invoices_org_id'), 'invoices', ['org_id'], unique=False)
    op.create_table('po_lines',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('po_id', sa.UUID(), nullable=False),
    sa.Column('erp_ref', sa.String(length=140), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('item_code', sa.String(length=140), nullable=False),
    sa.Column('description', sa.String(length=300), server_default='', nullable=False),
    sa.Column('hsn', sa.String(length=10), nullable=True),
    sa.Column('uom', sa.String(length=40), nullable=True),
    sa.Column('qty', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('rate', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('tax_rate', sa.Numeric(precision=7, scale=4), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_po_lines_org_id_orgs')),
    sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id'], name=op.f('fk_po_lines_po_id_purchase_orders')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_po_lines')),
    sa.UniqueConstraint('org_id', 'erp_ref', name=op.f('uq_po_lines_org_id'))
    )
    op.create_index(op.f('ix_po_lines_org_id'), 'po_lines', ['org_id'], unique=False)
    op.create_index(op.f('ix_po_lines_po_id'), 'po_lines', ['po_id'], unique=False)
    op.create_table('erp_outbox',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=True),
    sa.Column('request_id', sa.UUID(), nullable=True),
    sa.Column('state', sa.String(length=10), server_default='PENDING', nullable=False),
    sa.Column('erp_doc_name', sa.String(length=140), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("doc_type IN ('purchase_invoice', 'purchase_order')", name=op.f('ck_erp_outbox_doc_type')),
    sa.CheckConstraint("state IN ('PENDING', 'SENT', 'CONFIRMED', 'FAILED', 'UNKNOWN')", name=op.f('ck_erp_outbox_state')),
    sa.CheckConstraint('(invoice_id IS NULL) <> (request_id IS NULL)', name=op.f('ck_erp_outbox_one_source')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_erp_outbox_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_erp_outbox_org_id_orgs')),
    sa.ForeignKeyConstraint(['request_id'], ['purchase_requests.id'], name=op.f('fk_erp_outbox_request_id_purchase_requests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_erp_outbox')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_erp_outbox_idempotency_key'))
    )
    op.create_index(op.f('ix_erp_outbox_org_id'), 'erp_outbox', ['org_id'], unique=False)
    op.create_table('extractions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.String(length=200), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('raw_output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('field_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_extractions_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_extractions_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extractions'))
    )
    op.create_index(op.f('ix_extractions_invoice_id'), 'extractions', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_extractions_org_id'), 'extractions', ['org_id'], unique=False)
    op.create_table('field_edits',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('field', sa.String(length=80), nullable=False),
    sa.Column('old', sa.Text(), nullable=True),
    sa.Column('new', sa.Text(), nullable=True),
    sa.Column('edited_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['edited_by'], ['users.id'], name=op.f('fk_field_edits_edited_by_users')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_field_edits_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_field_edits_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_edits'))
    )
    op.create_index(op.f('ix_field_edits_invoice_id'), 'field_edits', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_field_edits_org_id'), 'field_edits', ['org_id'], unique=False)
    op.create_table('grn_lines',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('receipt_id', sa.UUID(), nullable=False),
    sa.Column('erp_ref', sa.String(length=140), nullable=False),
    sa.Column('po_line_id', sa.UUID(), nullable=True),
    sa.Column('item_code', sa.String(length=140), nullable=False),
    sa.Column('qty_received', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_grn_lines_org_id_orgs')),
    sa.ForeignKeyConstraint(['po_line_id'], ['po_lines.id'], name=op.f('fk_grn_lines_po_line_id_po_lines')),
    sa.ForeignKeyConstraint(['receipt_id'], ['goods_receipts.id'], name=op.f('fk_grn_lines_receipt_id_goods_receipts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grn_lines')),
    sa.UniqueConstraint('org_id', 'erp_ref', name=op.f('uq_grn_lines_org_id'))
    )
    op.create_index(op.f('ix_grn_lines_org_id'), 'grn_lines', ['org_id'], unique=False)
    op.create_index(op.f('ix_grn_lines_po_line_id'), 'grn_lines', ['po_line_id'], unique=False)
    op.create_index(op.f('ix_grn_lines_receipt_id'), 'grn_lines', ['receipt_id'], unique=False)
    op.create_table('invoice_lines',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=300), server_default='', nullable=False),
    sa.Column('item_code', sa.String(length=140), nullable=True),
    sa.Column('hsn', sa.String(length=10), nullable=True),
    sa.Column('qty', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('rate', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('po_line_id', sa.UUID(), nullable=True),
    sa.Column('pairing_method', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_invoice_lines_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_invoice_lines_org_id_orgs')),
    sa.ForeignKeyConstraint(['po_line_id'], ['po_lines.id'], name=op.f('fk_invoice_lines_po_line_id_po_lines')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_lines'))
    )
    op.create_index(op.f('ix_invoice_lines_invoice_id'), 'invoice_lines', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_invoice_lines_org_id'), 'invoice_lines', ['org_id'], unique=False)
    op.create_table('match_results',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('rule_set_version', sa.String(length=40), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('amount_at_risk', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('inputs_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rule_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome IN ('matched', 'exception', 'stale')", name=op.f('ck_match_results_outcome')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_match_results_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_match_results_org_id_orgs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_match_results'))
    )
    op.create_index(op.f('ix_match_results_invoice_id'), 'match_results', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_match_results_org_id'), 'match_results', ['org_id'], unique=False)
    op.create_table('review_decisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('reviewer_id', sa.UUID(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('approve', 'reject', 'request_correction')", name=op.f('ck_review_decisions_decision')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_review_decisions_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], name=op.f('fk_review_decisions_org_id_orgs')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_review_decisions_reviewer_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_decisions'))
    )
    op.create_index(op.f('ix_review_decisions_invoice_id'), 'review_decisions', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_review_decisions_org_id'), 'review_decisions', ['org_id'], unique=False)
    # --- App role and grants (§5). Role names are cluster-wide, so create it only if missing.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'orrfin_app') THEN
                CREATE ROLE orrfin_app NOLOGIN;
            END IF;
        END $$;
    """)
    # A non-superuser owner (e.g. the RDS master user) must be a member to SET ROLE.
    op.execute("GRANT orrfin_app TO CURRENT_USER")
    op.execute("GRANT USAGE ON SCHEMA public TO orrfin_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO orrfin_app")
    # The audit trail is append-only for the application.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM orrfin_app")
    # Only migrations (the owner) change the schema version.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM orrfin_app")
    # Tables added by later migrations get the normal app grants automatically.
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO orrfin_app")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
               "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM orrfin_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM orrfin_app")
    # The role itself is left in place: other databases on the server may use it.
    op.drop_index(op.f('ix_review_decisions_org_id'), table_name='review_decisions')
    op.drop_index(op.f('ix_review_decisions_invoice_id'), table_name='review_decisions')
    op.drop_table('review_decisions')
    op.drop_index(op.f('ix_match_results_org_id'), table_name='match_results')
    op.drop_index(op.f('ix_match_results_invoice_id'), table_name='match_results')
    op.drop_table('match_results')
    op.drop_index(op.f('ix_invoice_lines_org_id'), table_name='invoice_lines')
    op.drop_index(op.f('ix_invoice_lines_invoice_id'), table_name='invoice_lines')
    op.drop_table('invoice_lines')
    op.drop_index(op.f('ix_grn_lines_receipt_id'), table_name='grn_lines')
    op.drop_index(op.f('ix_grn_lines_po_line_id'), table_name='grn_lines')
    op.drop_index(op.f('ix_grn_lines_org_id'), table_name='grn_lines')
    op.drop_table('grn_lines')
    op.drop_index(op.f('ix_field_edits_org_id'), table_name='field_edits')
    op.drop_index(op.f('ix_field_edits_invoice_id'), table_name='field_edits')
    op.drop_table('field_edits')
    op.drop_index(op.f('ix_extractions_org_id'), table_name='extractions')
    op.drop_index(op.f('ix_extractions_invoice_id'), table_name='extractions')
    op.drop_table('extractions')
    op.drop_index(op.f('ix_erp_outbox_org_id'), table_name='erp_outbox')
    op.drop_table('erp_outbox')
    op.drop_index(op.f('ix_po_lines_po_id'), table_name='po_lines')
    op.drop_index(op.f('ix_po_lines_org_id'), table_name='po_lines')
    op.drop_table('po_lines')
    op.drop_index(op.f('ix_invoices_org_id'), table_name='invoices')
    op.drop_index('ix_invoices_duplicate_key', table_name='invoices')
    op.drop_table('invoices')
    op.drop_index(op.f('ix_request_lines_request_id'), table_name='request_lines')
    op.drop_index(op.f('ix_request_lines_org_id'), table_name='request_lines')
    op.drop_table('request_lines')
    op.drop_index(op.f('ix_request_approvals_request_id'), table_name='request_approvals')
    op.drop_index(op.f('ix_request_approvals_org_id'), table_name='request_approvals')
    op.drop_table('request_approvals')
    op.drop_index(op.f('ix_purchase_orders_org_id'), table_name='purchase_orders')
    op.drop_table('purchase_orders')
    op.drop_index(op.f('ix_purchase_requests_org_id'), table_name='purchase_requests')
    op.drop_table('purchase_requests')
    op.drop_index(op.f('ix_sessions_org_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('ix_jobs_status_run_after', table_name='jobs')
    op.drop_index(op.f('ix_jobs_org_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_goods_receipts_org_id'), table_name='goods_receipts')
    op.drop_table('goods_receipts')
    op.drop_index(op.f('ix_documents_org_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_categories_org_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_index(op.f('ix_audit_events_org_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_entity_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index(op.f('ix_vendors_org_id'), table_name='vendors')
    op.drop_table('vendors')
    op.drop_index('uq_users_email_lower', table_name='users')
    op.drop_index(op.f('ix_users_org_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_approval_policies_org_id'), table_name='approval_policies')
    op.drop_table('approval_policies')
    op.drop_table('orgs')
