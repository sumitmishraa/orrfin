# Orrfin architecture (one page)

The full design is in [BUILD_PLAN.md](BUILD_PLAN.md) §4. This page says what exists **now** and where it lives.
Status (15 Nov 2026): Steps 1–27 (the P2P Control Gate) and the v3.0 platform Steps 30–38 are built ([ADR 0009](adr/0009-platform-expansion.md)); Steps 39–40 tidied this page. Deploy (Step 28) and final review (Step 29) come next.

## Components

```
Browser ──► web (Next.js 16, :3000) ──► api (FastAPI, :8000) ──► Postgres 16 (Docker locally, RDS on AWS)
Supplier ─► web /portal (own cookie) ─┘        │
MCP client ─────────── POST /mcp (API key) ────┘     worker (same code, `python -m app.worker`) ──► jobs table
```

| Component | Folder | What it does |
|---|---|---|
| Web app | `frontend/` | Employee app in the shell (`components/shell/`), supplier portal under `/portal`, invitation page `/join`; calls the API through `/api/*`. Shared kit in `components/ui/` (DataTable, Dialog/Sheet, menus, tabs, avatars, status pills, toasts) |
| API | `backend/app/` | One FastAPI app; each product is a module under `app/modules/` with its own router |
| Worker | `backend/app/worker.py` | Runs jobs from the `jobs` table: extract, match, ERP pull/push, mock bank, webhook delivery |
| Database | `infra/docker-compose.yml` | Postgres 16; the app runs as the restricted `orrfin_app` role with row-level security per org |
| CI | `.github/workflows/ci.yml` | Migrations + pytest against Postgres |

## v3.0 platform modules (Steps 30–38)

| Module | Product | Notes |
|---|---|---|
| `modules/entities/` | Legal entities, currencies, FX table | Entity carries the tax regime (in_gst / ae_vat) used by matching |
| `modules/workflow_engine/` | Workflow engine | Versioned definitions, validator, simulator; second admin for lowering approvals (ADR 0010) |
| `modules/intake_forms/` | Intake management | Request types and extra questions; answers feed workflow rules as `custom.<key>` |
| `modules/notifications/`, `modules/integrations/` | Notifications, API keys, signed webhooks | Keys hashed; webhooks HMAC-signed with an SSRF allow-list |
| `modules/suppliers/`, `modules/supplier_risk/` | Supplier onboarding, portal, risk | Separate login realm; pure `rules.py` (§6e); critical risk holds POs and payments |
| `modules/sourcing/` | Sourcing | Sealed quotes, pure `compare.py` (§6f), human award → normal draft request |
| `modules/contracts/` | Contracts | AI/pattern proposals must quote the PDF; a person confirms every term |
| `modules/payments/` (+ `banking.py`), `modules/cards/` | Global payments, vendor cards | Simulated only: one currency per run, IBAN/SWIFT checks, mock card issuer |
| `modules/agents/`, `app/mcp_server.py` | AI concierge, superagents, workflow-builder agent, MCP | Read + propose only; proposals are single-use and submitted by their person |
| `infra/` + Dockerfiles | Demo server (Step 28): `docker-compose.prod.yml` (postgres, api, worker, web, caddy), `Caddyfile` (HTTPS), `deploy.sh` (one-command deploy) | Only Caddy is reachable (80/443); secrets in `.env.production` on the server; guide in `docs/DEPLOY_AWS.md` |
| `modules/ordering/` | Orrfin POs built from approved needs (Step 42, ADR 0012) | Need-first orgs only; merges the same item across requests; PO chain = amount tiers minus the manager; builder can't approve; one ERP draft PO per Orrfin PO; simulated vendor email |
| `modules/team/` | Team members, power seats, invitations (Step 41, ADR 0011) | Admin only; single-use hashed links; last-admin and own-role guards; deactivate, never delete |
| `modules/spend/`, `modules/documents/`, `modules/app_studio/` | Spend insights, PDFs, App Studio | Deterministic cube per currency; PDFs from records; App Studio objects are data, not code |
| `adapters/dialects.py`, `dialect_rest.py`, `dialect_rest_sim.py` | 8 more ERPs (all simulated) | One shared adapter, one field map per ERP; same contract and lost-reply suites |
| `auth/totp.py`, `security/http.py`, `db.py` | Security | Two-step sign-in, CSRF guard and headers, row-level security per org ([SECURITY_REVIEW.md](SECURITY_REVIEW.md)) |

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
| `backend/app/modules/sync/` | ERP pull from the org's active connection (upsert by `erp_connection_id` + `erp_ref`, skip unchanged) and the read-only vendor/PO routes |
| `backend/app/modules/connectors/` | The Connectors page API: save encrypted keys, Test connection, Prepare demo data (job), Make active, Disconnect; one active connection per org (ADR 0006) |
| `backend/app/modules/erp_outbox/` | §8 write-back: queue on approval (same transaction), `erp_push` job (SENT committed before the call; UNKNOWN → look up first), Retry sync; generic over doc type and ERP |
| `backend/app/security/` | `secrets.py` (Fernet encryption of ERP keys with `ORRFIN_SECRET_KEY`), `outbound.py` (ERP host allow-list, no redirects, timeouts, error → FAILED/UNKNOWN mapping, `redact()`) |
| `backend/app/erp_demo/canonical.py` | The one canonical demo dataset (5 vendors, 8 POs, 8 receipts) every connector renders and seeds from |
| `backend/app/modules/audit/service.py` | `record_event` (hash-chained per entity) and `verify_chain` |
| `backend/app/jobs.py`, `worker.py` | Postgres job queue (`SKIP LOCKED`, retries, stale-job recovery) and its worker process |
| `backend/app/modules/invoices/` | Upload, `extract` job, validation (`validation.py`), edits/confirm, `match_job.py` (DB ↔ engine bridge) |
| `backend/app/modules/matching/` | **Pure** §6 rules engine: `engine.py`, `config.py` (version, tolerances, risk weights), template `explain.py` |
| `backend/app/modules/review/` | Invoice decisions with SoD, re-match, audit list/timeline/verify, Control Graph |
| `backend/app/modules/insights/` | Control dashboard numbers (`GET /insights/summary`): deterministic SQL, role-scoped like the pages; later modules add sections through `SECTION_PROVIDERS` |
| `backend/app/modules/payments/` | Simulated payments (ADR 0008): pure `tds.py` (§6c) and `risk.py` (§6b); `service.py` profiles with maker-checker, runs with SoD, bank file, mock bank job `bank_settle` (idempotent, writes a statement CSV) |
| `backend/app/modules/bank/` | Bank reconciliation: pure `reconcile.py` (UTR → matched; amount + date ±3 days + vendor → suggested), statement CSV import, accept/unmatch |
| `backend/app/modules/close/` | Month-end close cockpit: live checklist (+ `EXTRA_CHECKS` hook), received-not-invoiced report (no journal), close/reopen, period lock; dashboard section `close` |
| `backend/app/modules/gst/` | GSTR-2B ITC matching (no filing): pure `match.py` (GSTIN + normalised invoice no + fiscal year, ±₹1), JSON import, `/gstr2b`; registers the payment hold, the close check and the dashboard section `gst` |
| `backend/app/modules/assistant/` | Orrfin Assistant (ADR 0007): `tools.py` read-only tools bound to the user (reuse the pages' loaders), `service.py` links/₹ check/rate limit/log, `POST /assistant/ask`; port `ports/assistant.py`, adapters `gemini_assistant.py`, `claude_assistant.py`, `fake_assistant.py` |
| `backend/app/modules/workflows/` | My tasks (derived), overdue + nudge, WhatsApp preview text, exception tasks (questions on held invoices), workflow settings, budgets (warnings only); plugs dashboard sections and the invoice questions panel in through hooks |
| `backend/app/modules/rules/` | Rules page: IF/THEN view of every control; admins edit approval tiers (validated, audited, new chains only) and category buyers |
| `backend/app/adapters/ai_prompts.py`, `gemini_ai.py`, `claude_ai.py`, `fake_extractor.py`, `local_filestore.py` | Shared AI prompts; Gemini extraction + explanation (working provider, ADR 0005); Claude (Bedrock / Anthropic API); labelled answer-key stand-in; local file store |
| `backend/app/errors.py` | Business refusals (403/404/409/422) with plain-English reasons |
| `backend/app/seed_demo.py` | Demo org, 5 users, 3 categories, 3 approval tiers (idempotent) |
| `backend/app/ports/` | Interfaces: Extractor, ErpAdapter, FileStore, Clock |
| `backend/app/adapters/` | Implementations of the ports; the only place ERP-specific field names may appear. `registry.py` = the connector catalogue (fields, host rules, simulated/live factories) and `get_adapter()`. Per ERP: `<erp>.py` translates documents, `<erp>_client.py` is the HTTP adapter, `<erp>_sim.py` is the in-process simulated server (httpx MockTransport) used in simulated mode and tests, `<erp>_fixtures.py` renders the canonical dataset; `sim_store.py` persists simulated writes. Catalogue and per-ERP mapping: [ERP_CONNECTORS.md](ERP_CONNECTORS.md) |
| `frontend/src/app/(app)/` | Logged-in pages: Inbox, Requests, Invoices (list, upload, review/match/decision), POs, Vendors, Audit, Control Graph, Trust, Connectors (admin) |
| `frontend/src/proxy.ts`, `next.config.ts` | Redirect to /login without a session cookie; `/api/*` is forwarded to FastAPI (same-origin cookie) |
| `backend/alembic/` | Migrations (additive only during demo week) |
| `backend/tests/` | `unit/`, `integration/`, `contract/` (`test_erp_adapter_contract.py` runs every adapter in `erp_adapters.py`), `failure/` (Step 14) |
| `frontend/src/styles/tokens.css` | Brand colours from `docs/BRAND.md` |
| `frontend/src/app/globals.css` | Maps brand tokens to Tailwind + shadcn/ui theme names |
| `frontend/src/components/ui/` | shadcn/ui components |
| `backend/scripts/` | One-off tools: `make_sample_invoice.py` (synthetic GST PDF), `bedrock_spike.py` (Step 2 Bedrock proof) |
| `seed/invoices/` | The single Step 2 Bedrock-spike invoice and its ground-truth `.expected.json` |
| `evals/extraction/` | Also `report.md` (latest real-AI eval) and `report-fake-baseline.md` (harness check). |
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
- [ADR 0003](adr/0003-ai-provider-and-fake-extractor.md): one AI port, three providers; the answer-key stand-in is always labelled; AI outages fall back to manual entry.
- [ADR 0008](adr/0008-simulated-payments.md): payments are simulated (bank file + mock bank), rule-based TDS and risk checks, maker-checker bank details, no ledger.
- [ADR 0007](adr/0007-assistant-agent.md): the assistant is read-only, runs with the user's permissions, links only to records its tools returned, and ₹-checks its answers.
- [ADR 0004](adr/0004-multi-erp-connectors.md): one ERP port, 11 connectors, each labelled Live / Sandbox / Simulated; write-back built once against the port.
- [ADR 0009](adr/0009-platform-expansion.md): the platform products are modules of this one application; product-to-module map; safety rules unchanged.
- [ADR 0010](adr/0010-workflow-engine.md): workflows are versioned definitions run by a deterministic interpreter; AI may draft, an admin publishes; the engine routes but never authorises.
