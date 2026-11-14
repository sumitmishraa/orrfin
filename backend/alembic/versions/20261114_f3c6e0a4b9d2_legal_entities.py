"""Step 31 (BUILD_PLAN v3.0 change 38, §5, §6d): legal entities, entity memberships and exchange rates.

Additive only. Every existing org gets one default entity (India, INR, GST), so every document
that has no `entity_id` keeps being checked exactly as before. `invoices.vat` holds the single
tax amount of a UAE invoice.

Revision ID: f3c6e0a4b9d2
Revises: e2b5d9f3a8c1
Create Date: 2026-11-14 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c6e0a4b9d2"
down_revision: str | None = "e2b5d9f3a8c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENCIES = "('INR', 'AED', 'USD', 'EUR')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "legal_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("tax_regime", sa.String(length=10), nullable=False),
        sa.Column("tax_id", sa.String(length=15), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("erp_connection_id", sa.UUID(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("tax_regime IN ('in_gst', 'ae_vat')", name=op.f("ck_legal_entities_tax_regime")),
        sa.CheckConstraint(f"base_currency IN {CURRENCIES}", name=op.f("ck_legal_entities_base_currency")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_legal_entities_org_id_orgs")),
        sa.ForeignKeyConstraint(["erp_connection_id"], ["erp_connections.id"],
                                name=op.f("fk_legal_entities_erp_connection_id_erp_connections")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_entities")),
        sa.UniqueConstraint("org_id", "name", name=op.f("uq_legal_entities_org_id")),
    )
    op.create_index(op.f("ix_legal_entities_org_id"), "legal_entities", ["org_id"])
    op.create_index("uq_legal_entities_one_default", "legal_entities", ["org_id"], unique=True,
                    postgresql_where=sa.text("is_default"))

    op.create_table(
        "entity_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_entity_memberships_org_id_orgs")),
        sa.ForeignKeyConstraint(["entity_id"], ["legal_entities.id"],
                                name=op.f("fk_entity_memberships_entity_id_legal_entities")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_entity_memberships_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_memberships")),
        sa.UniqueConstraint("entity_id", "user_id", name=op.f("uq_entity_memberships_entity_id")),
    )
    op.create_index(op.f("ix_entity_memberships_org_id"), "entity_memberships", ["org_id"])
    op.create_index(op.f("ix_entity_memberships_entity_id"), "entity_memberships", ["entity_id"])

    op.create_table(
        "fx_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("entered_by", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("rate > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.CheckConstraint("base_currency <> quote_currency", name=op.f("ck_fx_rates_two_currencies")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_fx_rates_org_id_orgs")),
        sa.ForeignKeyConstraint(["entered_by"], ["users.id"], name=op.f("fk_fx_rates_entered_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rates")),
        sa.UniqueConstraint("org_id", "base_currency", "quote_currency", "as_of", name=op.f("uq_fx_rates_org_id")),
    )
    op.create_index(op.f("ix_fx_rates_org_id"), "fx_rates", ["org_id"])

    op.add_column("invoices", sa.Column("entity_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_invoices_entity_id_legal_entities"), "invoices", "legal_entities",
                          ["entity_id"], ["id"])
    op.add_column("invoices", sa.Column("vat", sa.Numeric(18, 2), nullable=True))
    op.add_column("purchase_requests", sa.Column("entity_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_purchase_requests_entity_id_legal_entities"), "purchase_requests",
                          "legal_entities", ["entity_id"], ["id"])

    # One default entity per existing org. Its tax number is unknown here; an admin fills it in.
    op.execute(
        "INSERT INTO legal_entities (id, org_id, name, country, base_currency, tax_regime, is_default) "
        "SELECT gen_random_uuid(), id, name, 'IN', 'INR', 'in_gst', true FROM orgs")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_purchase_requests_entity_id_legal_entities"), "purchase_requests", type_="foreignkey")
    op.drop_column("purchase_requests", "entity_id")
    op.drop_column("invoices", "vat")
    op.drop_constraint(op.f("fk_invoices_entity_id_legal_entities"), "invoices", type_="foreignkey")
    op.drop_column("invoices", "entity_id")
    op.drop_table("fx_rates")
    op.drop_table("entity_memberships")
    op.drop_table("legal_entities")
