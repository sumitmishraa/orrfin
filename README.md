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

## How to run on a Mac (or Linux)

You need only **Docker Desktop** (docker.com → Download for Mac, pick Apple chip or Intel chip) and git.

1. Get the code (branch `platform-v3`):
   ```
   git clone --branch platform-v3 https://github.com/sumitmishraa/orrfin.git
   cd orrfin
   ```
2. Open Docker Desktop and wait until it says *Engine running*.
3. Start everything (the first build takes 5–10 minutes):
   ```
   ./scripts/demo-local.sh
   ```
4. Open **https://localhost**. The browser warns about the certificate the first time:
   - Chrome: **Advanced → Proceed to localhost**;
   - Safari: **Show Details → visit this website**.
5. Sign in with the demo logins below.
6. Stop with `./scripts/demo-local.sh --stop`, or start again from scratch with `./scripts/demo-local.sh --reset`.

This runs the same containers as the AWS server. To read or change the code, open the folder in VS Code or Cursor. To run the backend tests on a Mac, see "Tests" below: they need Python 3.12 and the local Postgres from `infra/docker-compose.yml`.

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

## Demo link on AWS (Step 28)

Follow [docs/DEPLOY_AWS.md](docs/DEPLOY_AWS.md): create one Ubuntu server in Mumbai, clone this repo, run
`sudo bash infra/deploy.sh`. It prints the HTTPS demo link and a new random demo password (the password
above stays for the laptop only).

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```
Database tests use a separate `orrfin_test` database (your demo data is never touched). They run when
Postgres is up (start it with `dev.ps1`) and are skipped otherwise. CI runs all tests against a real
Postgres on every push.

## Team and invitations (Step 41)

1. Sign in as Anita (admin) → **Settings → Team & roles** (or Ctrl K → "Invite teammates").
2. **Invite teammates**: paste emails, pick a role (requesters are free; others use one of 10 power seats), send.
3. Copy a link (or ⋯ → **Resend with a new link** on Pending invites) and open it in a private window.
   Locally there is no mail server: the "email" is a line in the API log.
4. On `/join`, set a name and password. Finance and admin invitees are sent to switch on two-step sign-in.
5. Back as Anita: click the new member to change role, limit, manager, or **Deactivate** (signs them out at once).
   You can't change your own role or limit, and the last admin can't be removed.

## Intake to procure, need first (Step 42)

The demo company works the way most Indian companies buy: the employee asks, the General Manager approves the
need, procurement chooses the vendor and price and sends one PO per vendor. Passwords are in "Demo logins".

1. **Riya (employee)**: *+* → **Paste a WhatsApp / email message** → paste
   `Hi Neha, we need 20 boxes of A4 paper for the Pune office. Thanks, Riya` → **Read the message** →
   choose *Office supplies* → **Send to my manager**. Status: *Waiting for manager*.
2. **Neha (General Manager)**: **My tasks** → the request → **Approve the need**. Status: *With procurement*.
3. **Arjun (procurement)**: **Procure → Orders → Approved needs**: tick the A4 lines (Riya's and Sameer's
   seeded ones) → **Create PO** → vendor *Shreeji*, item *STAT-A4-75* (last price filled in) → **Create draft PO**
   → **Submit**. Above ₹50,000 it waits for Finance; at or below, it is approved at once.
4. **Vikram (finance)**: **My tasks** → the PO → **Approve**. Arjun cannot approve his own PO (try it: 403).
5. **Arjun**: wait a few seconds for *ERP draft created · PUR-ORD-…*, then **Send to vendor** → check the email,
   the PDF and the WhatsApp preview → **Send email** (simulated). Riya's request now shows *Ordered*.

## Rules

No secrets in the repo (only `.env.example` is committed). No payments, GST filing or ledger posting.
See [CLAUDE.md](CLAUDE.md) for the full list.
