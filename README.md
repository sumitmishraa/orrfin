# Orrfin Control Gate

A 7-day investor prototype: supplier invoices are read by AI, checked line by line against ERPNext purchase
orders and goods receipts by deterministic rules, approved by a named person, and only then written to
ERPNext as a **draft** bill. Synthetic data only; not production.

- Plan (source of truth): [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md)
- Build steps: [docs/PROMPTS.md](docs/PROMPTS.md) · progress log: [docs/PROGRESS.md](docs/PROGRESS.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · brand colours: [docs/BRAND.md](docs/BRAND.md)

## How to run locally (Windows)

**You need:** Docker Desktop, Python 3.12, Node.js (22 or 24 LTS recommended; 26 works), Git.

1. Open this folder in VS Code, then open a terminal (**Terminal → New Terminal**).
2. Start everything:
   ```powershell
   .\scripts\dev.ps1
   ```
   The first run takes a few minutes: it creates `.env` from `.env.example`, sets up Python and web packages,
   and downloads Postgres. It opens Docker Desktop for you if it isn't running.
3. Open in your browser:
   - App: http://localhost:3000 (should say **Orrfin Control Gate** and **API connected**)
   - API health: http://localhost:8000/health → `{"status":"ok"}`
   - API docs: http://localhost:8000/docs
4. Stop everything:
   ```powershell
   .\scripts\dev.ps1 -Stop
   ```

**Port 3000 already taken** (another project's dev server)? Run `.\scripts\dev.ps1 -WebPort 3001` and open
http://localhost:3001 instead.

**Something failed?** Logs are in `.dev\api.err.log` and `.dev\web.err.log`.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```
The database test runs when Postgres is up (start it with `dev.ps1`) and is skipped otherwise. CI runs all
tests against a real Postgres on every push.

## Rules

No secrets in the repo (only `.env.example` is committed). No payments, GST filing or ledger posting.
See [CLAUDE.md](CLAUDE.md) for the full list.
