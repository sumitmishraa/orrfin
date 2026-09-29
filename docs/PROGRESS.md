# Build progress (handoff log)

Each step appends 8 lines or fewer: what was built, how to view it, open issues. New sessions read this file instead of re-reading the codebase.

## Current state
- Step 0 (manual setup): Docker done; Bedrock access **pending** (founder parked it on 29 Sep; Step 2 needs it).
- Step 1: done (29 Sep). Next: Step 3 (Bedrock still pending; Steps 3-5 need no AI). Steps renumbered in v2.1 (15 steps).

## Decisions so far
- Plan: docs/BUILD_PLAN.md v2.1 (intake-to-procure + draft PO added 29 Sep). Prompts: docs/PROMPTS.md (15 steps).
- Local development: Docker Desktop + Postgres 16 in Docker; files on local disk (S3 at deploy).
- AI: Claude via AWS Bedrock from Step 2, using the laptop user `orrfin-dev-laptop` (Bedrock-only permissions, configured with `aws configure`).
- ERP: fake ERPNext fixtures first (Step 4); live Frappe Cloud trial from Step 11 (start the 14-day trial then).
- Colours: docs/BRAND.md (to be filled in by the founder).
- Environment notes: Python 3.12.10 installed; Node v26 (check LTS compatibility in Step 1).
- Docker Desktop 29.8.0 works (WSL2 backend; hello-world passed 26 Sep). The CLI is at `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`. Terminals opened before the install may not have it on PATH, so `scripts/dev.ps1` should fall back to that path.

## Log
**Plan v2.1 (29 Sep).** Founder approved: intake-to-procure (intake form, category routing to buyer, amount-based approval chain) + Orrfin drafts the PO in ERPNext via the outbox (`orrfin_ref` unique custom field). New role `buyer`; new tables categories, approval_policies, request_lines. New PROMPTS Step 5 (intake) and Step 13 (draft PO); pitch moved later, date TBD. Open: confirm approval tiers ₹50k/₹5L and categories (BUILD_PLAN §14 Q7). Out of scope: vendor quotes, new-vendor requests.

**Step 1 — skeleton (29 Sep).** FastAPI `/health` + settings + Alembic (no tables); Next.js 16.3 + Tailwind 4 + shadcn/ui (base-nova) with brand tokens in `frontend/src/styles/tokens.css`; Postgres 16 in `infra/docker-compose.yml`; `scripts/dev.ps1` (auto-opens Docker Desktop; `-Stop`; `-WebPort`); CI in `.github/workflows/ci.yml`; README, ARCHITECTURE.md.
- View: `.\scripts\dev.ps1` → http://localhost:3000 ("API connected"), http://localhost:8000/health, /docs. Verified: pytest 3/3 (incl. live DB), lint + build clean, browser shows API connected, -Stop works.
- Node 26.9 works with Next 16.3.6 (build and dev OK); no downgrade needed.
- Windows Smart App Control blocks psycopg's DLL → switched to pure-Python `pg8000` (docs/adr/0001).
- Port 3000 is often used by the founder's other project (wrfitzz-store); use `-WebPort 3001` then.
- Contrast: muted text darkened to #536a84 for WCAG AA (BRAND.md updated).
- Open: CI not yet run on GitHub (no remote configured). Starlette warns that `httpx` test client is deprecated; harmless for now.
