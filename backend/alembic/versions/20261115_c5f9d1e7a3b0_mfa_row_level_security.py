"""Step 38 (BUILD_PLAN v3.0 change 50, §9): two-step sign-in columns and Postgres row-level security.

Additive. Every business table with an `org_id` gets a policy: when a request has said which org it
works for (`app.org_id`, set by the API after sign-in), the database itself hides and refuses rows of
any other org, so a query that forgot its org filter still cannot leak. When `app.org_id` is not set
(the sign-in lookups, the worker, the supplier portal) the policy is open and the application's own
checks apply, exactly as before. The schema owner (migrations) is not subject to it.

Left out on purpose, because they are looked up before the org is known or must stay unique across
orgs: users, sessions, supplier_users, supplier_sessions, supplier_invites, api_keys, jobs.

Revision ID: c5f9d1e7a3b0
Revises: b4e8c0d6f2a9
Create Date: 2026-11-15 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f9d1e7a3b0"
down_revision: str | None = "b4e8c0d6f2a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXCLUDED = ("users", "sessions", "supplier_users", "supplier_sessions", "supplier_invites", "api_keys", "jobs")
POLICY = ("(nullif(current_setting('app.org_id', true), '') IS NULL "
          "OR org_id = nullif(current_setting('app.org_id', true), '')::uuid)")


def _tables() -> list[str]:
    rows = op.get_bind().execute(sa.text(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'org_id' "
        "AND table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
        "AND table_type = 'BASE TABLE') ORDER BY table_name"))
    return [r[0] for r in rows if r[0] not in EXCLUDED]


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    for table in _tables():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY org_isolation ON "{table}" USING {POLICY} WITH CHECK {POLICY}')


def downgrade() -> None:
    for table in _tables():
        op.execute(f'DROP POLICY IF EXISTS org_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_column("users", "mfa_last_step")
    op.drop_column("users", "mfa_enabled_at")
    op.drop_column("users", "mfa_secret_encrypted")
