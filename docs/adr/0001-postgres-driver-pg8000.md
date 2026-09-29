# ADR 0001: Use the pure-Python pg8000 Postgres driver

**Date:** 29 Sep 2026 · **Status:** accepted · **Step:** 1

## Context
The first choice was `psycopg[binary]` (psycopg 3). On the founder's Windows 11 laptop, importing it fails with
"DLL load failed ... An Application Control policy has blocked this file": Windows Smart App Control blocks the
DLL bundled with `psycopg-binary`. Other compiled packages (pydantic-core, SQLAlchemy, uvicorn extras) load fine.
Turning Smart App Control off is a laptop-wide security downgrade and is hard to undo, so we don't ask for it.

## Decision
Use `pg8000` (pure Python, maintained, supported by SQLAlchemy 2 and Alembic) everywhere: laptop, CI and AWS.
Connection URLs use `postgresql+pg8000://`. One driver everywhere avoids "works in CI, fails on the laptop".

## Consequences
- Somewhat slower than psycopg's C implementation; irrelevant at demo volumes.
- Connection errors surface as `InterfaceError` rather than `OperationalError`; catch `sqlalchemy.exc.DBAPIError`.
- Revisit before a pilot (BUILD_PLAN §12): switching back is a dependency and URL change only.
