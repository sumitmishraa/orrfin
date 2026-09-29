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
| `backend/app/models.py` | Every table in BUILD_PLAN §5 (+ `sessions`); money `NUMERIC`, statuses as CHECK constraints |
| `backend/app/auth/` | Login (argon2), server-side sessions, `current_user` and role guards |
| `backend/app/modules/` | Business modules: procurement, invoices, matching (pure), review, audit, sync |
| `backend/app/modules/procurement/service.py` | Intake → routing → approval chain; every §9 rule lives in `decision_refusal` |
| `backend/app/modules/sync/` | ERP pull (upsert by `erp_ref`, skip unchanged) and the read-only vendor/PO routes |
| `backend/app/modules/audit/service.py` | `record_event` (hash-chained per entity) and `verify_chain` |
| `backend/app/jobs.py`, `worker.py` | Postgres job queue (`SKIP LOCKED`, retries, stale-job recovery) and its worker process |
| `backend/app/errors.py` | Business refusals (403/404/409/422) with plain-English reasons |
| `backend/app/seed_demo.py` | Demo org, 5 users, 3 categories, 3 approval tiers (idempotent) |
| `backend/app/ports/` | Interfaces: Extractor, ErpAdapter, FileStore, Clock |
| `backend/app/adapters/` | Implementations of the ports; the only place ERPNext field names may appear (`erpnext.py` translates, `erpnext_fake.py` serves `seed/erpnext/`) |
| `frontend/src/app/(app)/` | Logged-in pages: Inbox, Requests (list, new, detail), POs, Vendors; Invoices/Audit are placeholders |
| `frontend/src/proxy.ts`, `next.config.ts` | Redirect to /login without a session cookie; `/api/*` is forwarded to FastAPI (same-origin cookie) |
| `backend/alembic/` | Migrations (additive only during demo week) |
| `backend/tests/` | `unit/`, `integration/` now; `contract/`, `failure/` later |
| `frontend/src/styles/tokens.css` | Brand colours from `docs/BRAND.md` |
| `frontend/src/app/globals.css` | Maps brand tokens to Tailwind + shadcn/ui theme names |
| `frontend/src/components/ui/` | shadcn/ui components |
| `backend/scripts/` | One-off tools: `make_sample_invoice.py` (synthetic GST PDF), `bedrock_spike.py` (Step 2 Bedrock proof) |
| `seed/invoices/` | The single Step 2 Bedrock-spike invoice and its ground-truth `.expected.json` |
| `evals/extraction/` | 12 evaluation invoices tied to the Step 4 POs, each with an answer key (built by `backend/scripts/make_eval_invoices.py`; table in `docs/DEMO_DATA.md`) |
| `scripts/dev.ps1` | Start/stop the local stack |
| `docs/adr/` | Short records of significant decisions |

## Rules that shape the code (BUILD_PLAN §4)
- `matching` imports no database, HTTP or AI code.
- Only `sync` calls `ErpAdapter`; only `invoices` calls `Extractor`.
- Every state change and its `audit_events` row are written in the same transaction.
- `org_id` on every business table; money is `NUMERIC(18,2)` / `Decimal`.

## Decisions
- [ADR 0001](adr/0001-postgres-driver-pg8000.md): pg8000 Postgres driver (Windows blocks psycopg's DLL).
- [ADR 0002](adr/0002-app-database-role.md): the app runs as the restricted `orrfin_app` role (`SET ROLE`), so it can't rewrite audit events.
