# ADR 0002: The app runs as a restricted database role

**Date:** 29 Sep 2026 · **Status:** accepted · **Plan:** BUILD_PLAN §5 (database grants), §9

## Context
BUILD_PLAN §5 says the application role gets only `INSERT, SELECT` on `audit_events`, and migrations run
as a separate owner role. A second login user would need a second password in `.env` and, on AWS, a second
secret, for a demo that runs on one laptop and then one server.

## Decision
- The first migration creates a `NOLOGIN` role `orrfin_app`, grants it `SELECT, INSERT, UPDATE, DELETE` on
  every table, and revokes `UPDATE, DELETE, TRUNCATE` on `audit_events` (and writes on `alembic_version`).
- The app keeps connecting as the schema owner, but runs `SET ROLE orrfin_app` on every new connection
  (`app/db.py`). Alembic uses its own engine, so migrations still run as the owner.
- Tests prove the app role cannot `UPDATE` or `DELETE` audit events (`tests/integration/test_audit_trail.py`).

## Consequences
- One password, one secret. The restriction covers every query the app makes.
- It is not a hard security boundary: code with the owner's login could `RESET ROLE`. Before a pilot with
  real data (§12), give `orrfin_app` its own login and password and drop the owner from the app's settings.
