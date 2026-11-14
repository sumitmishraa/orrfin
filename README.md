# Orrfin

A procurement platform built around the customer's existing ERP. It began as the P2P "Control Gate"
(supplier invoices read by AI, checked line by line against the ERP's purchase orders and goods receipts by
deterministic rules, approved by a named person, written back only as a **draft** bill) and, from plan v3.0,
adds supplier onboarding and a supplier portal, supplier risk, sourcing, contracts, a workflow engine and
intake forms, simulated global payments and vendor cards, spend insights, App Studio, an AI concierge with
superagents, an MCP server and 19 ERP connectors. Synthetic data only; payments and cards are simulated;
not production (see [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) for what is still open).

Where each product lives in the app: Procure (requests, POs), Pay (invoices, payments, vendor cards),
Suppliers (onboarding), Source (RFQs, contracts), Automate (workflow builder, App Studio, spend insights),
Home → Ask Orrfin (agents), Settings (connectors, legal entities, request forms, API & webhooks).
Suppliers use `/portal`.

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
| kabir.security@demo.orrfin.ai | Approver (IT security lead) | ₹0 | Decides the "IT security review" step on Software & SaaS requests |

Approval tiers (BUILD_PLAN §9): up to ₹50,000 → manager; up to ₹5,00,000 → manager then finance;
above → manager, finance, then admin.

**Try it:** log in as Vikram → **POs** → **Sync from ERP**. Then as Riya → **New request** (IT hardware,
3 laptops at ₹80,000) → Submit. As Arjun → open it from the Inbox → choose the vendor, item code
`IT-LAP-14-I5` → **Save and send for approval**. As Neha, then Vikram → **Approve**. The request shows
**Approved · ready for PO**.

## Invoices (Steps 7-10)

**AI reader:** set `AI_PROVIDER` in `.env` to `gemini` (the working choice for now: paste a key from
https://aistudio.google.com/apikey into `GEMINI_API_KEY`), `bedrock` (the target; needs Bedrock model access, see
`docs/spikes.md`), `anthropic` (with `ANTHROPIC_API_KEY`), or `fake`. See `docs/adr/0005-gemini-until-bedrock.md`. `fake` reads only the 12 evaluation
PDFs, from their answer keys, and every screen labels it "Simulated reading". Other PDFs go to manual entry.

**Try it:** as Vikram (finance) → **Invoices** → **Upload invoice PDF** → pick a file from `evals/extraction/`
→ check the fields → **Save and confirm for matching**. The match result appears with a plain-English reason.
Then as Anita (admin) → open it → **Approve** or **Reject** (Vikram can't approve it: whoever uploads an invoice can't approve it).
**Audit** shows every record's history and verifies its hash chain; **Control Graph** replays the chain.
Expected results for each PDF: `docs/DEMO_DATA.md`. Extraction accuracy: `evals/extraction/report.md`.

## ERP connectors (Steps 12-20)

Sign in as Anita (admin) → **Connectors**. Every ERP works in **Simulated** mode out of the box (fixtures in that
ERP's published API format). To connect a real free account: create it, then follow
[docs/CONNECT_ERPS.md](docs/CONNECT_ERPS.md) (paste keys → Test connection → Prepare demo data → Make active).
Keys are stored encrypted with `ORRFIN_SECRET_KEY`, which `scripts/dev.ps1` creates in `.env` (ADR 0006).

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
