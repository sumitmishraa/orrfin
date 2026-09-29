# Orrfin architecture (one page)

The full design is in [BUILD_PLAN.md](BUILD_PLAN.md) §4. This page says what exists **now** and where it lives.
Status: Step 1 (walking skeleton). No business tables or features yet.

## Components

```
Browser ──► web (Next.js, :3000) ──► api (FastAPI, :8000) ──► Postgres 16 (Docker locally, RDS on AWS)
```

| Component | Folder | What it does today | Comes later |
|---|---|---|---|
| Web app | `frontend/` | One placeholder page that checks the API is up | Login, intake requests and approvals, invoices, POs, audit (Steps 3–10) |
| API | `backend/app/` | `GET /health`; settings from env; DB engine | Business modules and routes |
| Worker | `backend/app/worker.py` | Not built yet | Jobs table loop: extract, erp_pull, erp_push for bills and POs (Steps 4, 7, 12, 13) |
| Database | `infra/docker-compose.yml` | Postgres 16, empty; Alembic ready | Schema from §5 (Step 3) |
| CI | `.github/workflows/ci.yml` | Migrations + pytest against Postgres | Same, with more tests |

## Folders

| Path | Contents |
|---|---|
| `backend/app/main.py` | App factory, CORS, `/health` |
| `backend/app/config.py` | All settings, read from env / repo-root `.env` |
| `backend/app/db.py` | SQLAlchemy engine, session, `Base` with constraint naming convention |
| `backend/app/modules/` | Business modules: procurement, invoices, matching (pure), review, audit, sync |
| `backend/app/ports/` | Interfaces: Extractor, ErpAdapter, FileStore, Clock |
| `backend/app/adapters/` | Implementations of the ports; the only place ERPNext field names may appear |
| `backend/alembic/` | Migrations (additive only during demo week) |
| `backend/tests/` | `unit/`, `integration/` now; `contract/`, `failure/` later |
| `frontend/src/styles/tokens.css` | Brand colours from `docs/BRAND.md` |
| `frontend/src/app/globals.css` | Maps brand tokens to Tailwind + shadcn/ui theme names |
| `frontend/src/components/ui/` | shadcn/ui components |
| `backend/scripts/` | One-off tools: `make_sample_invoice.py` (synthetic GST PDF), `bedrock_spike.py` (Step 2 Bedrock proof) |
| `seed/invoices/` | Synthetic invoice PDFs, each with a ground-truth `.expected.json` |
| `scripts/dev.ps1` | Start/stop the local stack |
| `docs/adr/` | Short records of significant decisions |

## Rules that shape the code (BUILD_PLAN §4)
- `matching` imports no database, HTTP or AI code.
- Only `sync` calls `ErpAdapter`; only `invoices` calls `Extractor`.
- Every state change and its `audit_events` row are written in the same transaction.
- `org_id` on every business table; money is `NUMERIC(18,2)` / `Decimal`.

## Decisions
- [ADR 0001](adr/0001-postgres-driver-pg8000.md): pg8000 Postgres driver (Windows blocks psycopg's DLL).
