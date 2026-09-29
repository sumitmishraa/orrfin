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
   - App: http://localhost:3000 → the login page (log in with a demo account below)
   - API health: http://localhost:8000/health → `{"status":"ok"}`
   - API docs: http://localhost:8000/docs
4. Stop everything:
   ```powershell
   .\scripts\dev.ps1 -Stop
   ```

`dev.ps1` also starts the **worker** (it runs background jobs such as "Sync from ERP") and loads the demo
data. Running it again never duplicates the demo data.

**Port 3000 already taken** (another project's dev server)? Run `.\scripts\dev.ps1 -WebPort 3001` and open
http://localhost:3001 instead.

**Something failed?** Logs are in `.dev\api.err.log`, `.dev\worker.err.log` and `.dev\web.err.log`.

## Demo logins (synthetic, local demo only)

Every demo account uses the password **`Orrfin@Demo2026`**. The people and company are fictional.

| Email | Role | Approval limit | Notes |
|---|---|---|---|
| riya.requester@demo.orrfin.ai | Requester | – | Her manager is Neha |
| arjun.buyer@demo.orrfin.ai | Buyer | – | Owns all three categories |
| neha.approver@demo.orrfin.ai | Approver | ₹5,00,000 | Approves as Riya's manager |
| vikram.finance@demo.orrfin.ai | Finance | ₹50,00,000 | |
| anita.admin@demo.orrfin.ai | Admin | ₹1,00,00,000 | Handles the admin queue |

Approval tiers (BUILD_PLAN §9): up to ₹50,000 → manager; up to ₹5,00,000 → manager then finance;
above → manager, finance, then admin.

**Try it:** log in as Vikram → **POs** → **Sync from ERP**. Then as Riya → **New request** (IT hardware,
3 laptops at ₹80,000) → Submit. As Arjun → open it from the Inbox → choose the vendor, item code
`IT-LAP-14-I5` → **Save and send for approval**. As Neha, then Vikram → **Approve**. The request shows
**Approved · ready for PO**.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```
Database tests use a separate `orrfin_test` database (your demo data is never touched). They run when
Postgres is up (start it with `dev.ps1`) and are skipped otherwise. CI runs all tests against a real
Postgres on every push.

## Rules

No secrets in the repo (only `.env.example` is committed). No payments, GST filing or ledger posting.
See [CLAUDE.md](CLAUDE.md) for the full list.
