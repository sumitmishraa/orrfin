"""Step 34 (BUILD_PLAN v3.0 changes 45-46, ADR 0008): payment runs per currency, SWIFT payees, vendor cards.

Additive only: new columns default to the old behaviour (INR runs, Indian NEFT/RTGS payees);
`vendor_payment_profiles.ifsc` becomes nullable and `bank_account` wider so an IBAN fits.
Everything stays simulated: a mock bank and a mock card issuer, never real money.

Revision ID: f2c6a8b4d0e7
Revises: e1b5d9a7c3f6
Create Date: 2026-11-14 21:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c6a8b4d0e7"
down_revision: str | None = "e1b5d9a7c3f6"
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
    op.add_column("payment_runs", sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False))
    op.add_column("vendor_payment_profiles", sa.Column("swift_bic", sa.String(length=11), nullable=True))
    op.alter_column("vendor_payment_profiles", "ifsc", existing_type=sa.String(length=11), nullable=True)
    op.alter_column("vendor_payment_profiles", "bank_account", existing_type=sa.String(length=20),
                    type_=sa.String(length=34))

    op.create_table(
        "vendor_cards",
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("holder_id", sa.UUID(), nullable=False),
        sa.Column("issued_by", sa.UUID(), nullable=False),
        sa.Column("issuer_ref", sa.String(length=40), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("limit_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("spent", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("merchant_lock", sa.String(length=120), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="active", nullable=False),
        sa.CheckConstraint("status IN ('active', 'frozen', 'closed')", name=op.f("ck_vendor_cards_status")),
        sa.CheckConstraint("spent <= limit_amount", name=op.f("ck_vendor_cards_within_limit")),
        sa.UniqueConstraint("issuer_ref", name=op.f("uq_vendor_cards_issuer_ref")),
        _fk("vendor_cards", "request_id", "purchase_requests"), _fk("vendor_cards", "holder_id", "users"),
        _fk("vendor_cards", "issued_by", "users"),
        *_base("vendor_cards"),
    )
    op.create_index(op.f("ix_vendor_cards_org_id"), "vendor_cards", ["org_id"])
    op.create_table(
        "card_transactions",
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("decline_reason", sa.String(length=200), nullable=True),
        sa.Column("auth_code", sa.String(length=12), nullable=True),
        sa.Column("invoice_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("status IN ('approved', 'declined')", name=op.f("ck_card_transactions_status")),
        _fk("card_transactions", "card_id", "vendor_cards"), _fk("card_transactions", "invoice_id", "invoices"),
        *_base("card_transactions"),
    )
    op.create_index(op.f("ix_card_transactions_org_id"), "card_transactions", ["org_id"])
    op.create_index(op.f("ix_card_transactions_card_id"), "card_transactions", ["card_id"])


def downgrade() -> None:
    op.drop_table("card_transactions")
    op.drop_table("vendor_cards")
    op.drop_column("vendor_payment_profiles", "swift_bic")
    op.drop_column("payment_runs", "currency")
