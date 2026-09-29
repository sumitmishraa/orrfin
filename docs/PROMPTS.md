# Orrfin Build: Step-by-Step Prompts

Copy one prompt at a time into Claude Code. Each prompt builds one small, testable piece and ends with something you can **see on your laptop**.

---

## How to use this file (and save credits)

1. **Start every step in a fresh session:** type `/clear`, then paste the prompt. Claude re-reads `CLAUDE.md` automatically, and each prompt tells it to read only `docs/PROGRESS.md` plus the exact plan sections it needs. That is far cheaper than a long conversation.
2. **Pick the model the prompt names** (`/model sonnet` for routine work, `/model opus` for the money logic and ERP write-back). Sonnet is cheaper; save Opus for the steps where mistakes cost money.
3. **After each build step, run the VERIFY prompt** at the bottom of this file, in a new session. Verifying is cheaper than building, and it catches mistakes before they pile up.
4. **If a step fails or runs out mid-way,** use the RESUME prompt. It reads `docs/PROGRESS.md` and continues from where things stopped.
5. **Keep replies short.** Every prompt asks for a reply of 12 lines or fewer. Don't ask for long explanations mid-build; ask afterwards if you need one.
6. **Don't paste documents into the chat.** Put them in `docs/` and name the file in your prompt.

**Where to look after each step:**

| What | Where |
|---|---|
| The app | http://localhost:3000 |
| The API and its interactive docs | http://localhost:8000/docs |
| The ERPNext demo system (from Step 10) | your Frappe Cloud URL |

**Starting and stopping everything:** after Step 1, run `.\scripts\dev.ps1` in the VS Code terminal to start everything, and `.\scripts\dev.ps1 -Stop` to stop it.

---

## Step 0 — Things you do by hand (no Claude, no credits)

Do these once, in order. Tick each one off.

- [ ] **Install Docker Desktop:** go to docker.com → Download for Windows → run the installer → keep "Use WSL 2" ticked → restart the PC → open Docker Desktop once and wait until it says "Engine running".
- [ ] **Create an AWS account and secure it:** follow BUILD_PLAN §10 **A** (MFA, the `orrfin-admin` user, a $50 budget, the Mumbai region).
- [ ] **Turn on Claude in Bedrock:** BUILD_PLAN §10 **D**, steps 1–2. Enable Anthropic Claude in the Model catalog and try one message in the Playground.
- [ ] **Create a laptop-only AI key** (so the app on your laptop can call Bedrock):
  1. IAM → Users → **Create user** `orrfin-dev-laptop`. Do **not** tick console access.
  2. Permissions → **Attach policies directly** → `AmazonBedrockLimitedAccess`. If it isn't listed, choose Create policy and allow only `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`.
  3. Open the user → **Security credentials** → **Create access key** → choose "Local code" → download the `.csv`.
  4. Install the AWS CLI (search "AWS CLI install Windows", then run the MSI).
  5. In a terminal, run `aws configure`. Paste the two keys from the `.csv`, set the region to `ap-south-1`, and set the output to `json`.
  6. **Never paste these keys into chat or into any project file.**
- [ ] **Create a free GitHub account**, and a **private** repository named `orrfin`.
- [ ] **Paste your colours** into `docs/BRAND.md`.
- [ ] **Recommended, saves credits:** tell Claude "turn off GateGuard's routine checks". It currently makes Claude explain every command twice.

---

## Step 1 — Project skeleton you can open in the browser

`/model sonnet` · **Skills:** `ecc:fastapi-patterns`, `ecc:docker-patterns`, `ecc:frontend-patterns`

```
STEP 1 — Skeleton. Read CLAUDE.md, docs/PROGRESS.md, docs/BRAND.md, and BUILD_PLAN §3–§4 only.
Use skills: ecc:fastapi-patterns, ecc:docker-patterns, ecc:frontend-patterns.
Build the repo layout from BUILD_PLAN §4:
- backend: FastAPI app with GET /health, config from env, Alembic set up (no tables yet).
- frontend: Next.js + Tailwind + shadcn/ui, with a design-token file built from docs/BRAND.md;
  one placeholder home page showing "Orrfin Control Gate".
- infra/docker-compose.yml: postgres:16 for local development.
- scripts/dev.ps1: starts postgres, api (port 8000) and web (port 3000); `-Stop` stops them all.
- .env.example (no real values), .gitignore, a README with "how to run locally".
- .github/workflows/ci.yml running pytest.
- docs/ARCHITECTURE.md (one page: components and folders).
Check the Node version: if it isn't 22 or 24 LTS and Next.js has issues, tell me instead of working around it.
Done when: dev.ps1 starts everything; localhost:3000 shows the page; localhost:8000/health returns ok; pytest passes.
Finish: append ≤8 lines to docs/PROGRESS.md, commit "step 1: skeleton", reply in ≤12 lines, including what I should open in the browser.
```

---

## Step 2 — Prove the AI can read an invoice (Bedrock spike)

`/model sonnet` · **Skills:** `claude-api`, `anthropic-skills:pdf`

```
STEP 2 — Bedrock spike. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §7 and §3 (AI row).
Use skills: claude-api, anthropic-skills:pdf.
- Generate 1 synthetic GST invoice PDF in seed/invoices/ (fake Indian vendor, valid-format GSTIN, 3 lines, CGST+SGST).
- Write backend/scripts/bedrock_spike.py: uses my AWS CLI profile (region ap-south-1), sends the PDF to Claude on Bedrock,
  and prints the extracted fields as JSON.
- Find the correct model / inference-profile ID callable from ap-south-1. Record it and the routing region
  (from CloudTrail or the response metadata, if available) in docs/spikes.md.
- Never print or store my AWS keys.
Done when: the script prints correct fields for the sample PDF.
Finish: update PROGRESS.md, commit "step 2: bedrock spike", reply ≤10 lines, including the model ID and anything I must do in the AWS console.
```

---

## Step 3 — Database, login and roles

`/model sonnet` · **Skills:** `ecc:postgres-patterns`, `ecc:database-migrations`, `ecc:tdd-workflow`

```
STEP 3 — Schema + auth. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 and §9.
Use skills: ecc:postgres-patterns, ecc:database-migrations, ecc:tdd-workflow.
- Alembic migration for every table in §5, with org_id, NUMERIC money, and the audit_events grants
  (app role: INSERT/SELECT only).
- Email + password login (argon2), session cookie, roles, approval_limit.
- Seed script: 1 org, 4 users (requester, approver, finance, admin). Put the demo passwords in the README.
- Frontend: a login page in brand colours, and a logged-in shell with navigation (Inbox, Invoices, Requests, POs, Audit).
Tests first: login works; wrong password fails; a data query from another org's session is refused; the app role cannot UPDATE audit_events.
Done when: tests pass and I can log in at localhost:3000 as each seeded user.
Finish: PROGRESS.md, commit "step 3", reply ≤12 lines, including the demo logins.
```

---

## Step 4 — Fake ERPNext: vendors, POs and receipts appear in Orrfin

`/model sonnet` · **Skills:** `ecc:hexagonal-architecture`, `ecc:api-connector-builder`, `explore-codebase`

```
STEP 4 — ERP adapter (fake first). Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2 and §4 (adapter rules).
Use skills: ecc:hexagonal-architecture, ecc:api-connector-builder, explore-codebase.
- ErpAdapter port. FakeErpnextAdapter reads JSON fixtures in seed/erpnext/ shaped exactly like the ERPNext REST responses
  (/api/resource/Supplier, Purchase Order, Purchase Receipt).
- Fixtures: 5 vendors, 8 POs (some partially received), matching receipts.
- Pull sync as a job in the jobs table + worker: upsert by erp_ref, skip if erp_modified is unchanged.
- UI: Vendors and POs pages; a PO detail page showing ordered vs received quantities; a "Sync from ERP" button.
Tests: contract tests on the fixtures; running the sync twice leaves row counts unchanged.
Done when: I click Sync and see the POs at localhost:3000.
Finish: PROGRESS.md, commit "step 4", reply ≤10 lines.
```

---

## Step 5 — Test invoices and an answer key

`/model sonnet` · **Skills:** `anthropic-skills:pdf`, `ecc:eval-harness`

```
STEP 5 — Synthetic invoices + eval set. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §6 and §7 (evaluation set).
Use skills: anthropic-skills:pdf, ecc:eval-harness.
Create 12 synthetic invoice PDFs in evals/extraction/, each with a ground-truth JSON, tied to the Step 4 POs:
clean match; 7% price variance; over-receipt quantity; partial receipt + second invoice; duplicate number; the same file twice;
bad GSTIN; IGST where CGST+SGST applies; vendor mismatch; closed PO; unpaired line; prompt-injection text inside the PDF.
Add docs/DEMO_DATA.md: a table of which file demonstrates what.
Done when: 12 PDFs + 12 JSON files exist and open correctly.
Finish: PROGRESS.md, commit "step 5", reply ≤8 lines.
```

---

## Step 6 — Upload an invoice and let the AI read it

`/model sonnet` · **Skills:** `claude-api`, `ecc:regex-vs-llm-structured-text`, `ecc:eval-harness`

```
STEP 6 — Extraction pipeline. Read CLAUDE.md, docs/PROGRESS.md, docs/spikes.md, BUILD_PLAN §7.
Use skills: claude-api, ecc:regex-vs-llm-structured-text, ecc:eval-harness.
- Extractor port + BedrockExtractor (model ID from spikes.md) + FakeExtractor (used in tests).
- FileStore port with a local-disk implementation (S3 comes in the deploy step).
- Upload → documents (sha256) → extract job → Pydantic schema with evidence per field → validation
  (GSTIN regex, dates, arithmetic) → extractions row storing model_id and prompt_version.
- UI: an upload page; an invoice review page with the PDF on the left and fields on the right,
  showing evidence on hover, highlighting failed checks, editable fields (every edit writes to field_edits + audit).
- Outage: 3 retries, then "manual entry" mode.
- Eval script: run all 12 PDFs and write evals/extraction/report.md with per-field accuracy.
Tests: validation rules; a job resumes after the worker is killed.
Done when: I upload a PDF at localhost:3000 and see the extracted fields; report.md exists.
Finish: PROGRESS.md, commit "step 6", reply ≤12 lines, including the accuracy numbers.
```

---

## Step 7 — The matching engine (the heart of the product)

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:python-testing`

```
STEP 7 — Matching engine. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 (duplicate key) and §6 in full.
Use skills: ecc:tdd-workflow, ecc:python-testing.
Write the tests FIRST for every rule in §6 and the ≥14 scenarios in §11 Day 4; then implement.
- The matching module is pure: no DB, HTTP or AI imports. Decimal only; ROUND_HALF_UP; tolerances in one config object;
  RULE_SET_VERSION stored with every result.
- Cumulative quantity uses invoiced_to_date. Line pairing follows the §6 order; ambiguous → LINE_UNPAIRED.
- amount_at_risk and a risk score from fixed weights.
- Explanation: Claude receives only the rule_results JSON (never document text) and returns plain English.
- Wire it up: after review confirmation → match job → match_results + audit.
Done when: all tests pass; uploading each of the 12 eval PDFs gives the outcome listed in DEMO_DATA.md.
Finish: PROGRESS.md, commit "step 7", reply ≤12 lines, with a pass/fail table.
```

---

## Step 8 — Exception inbox, approvals, segregation of duties, audit trail

`/model sonnet` · **Skills:** `ecc:fastapi-patterns`, `ecc:frontend-patterns`, `ecc:security-review`

```
STEP 8 — Review + controls. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 (audit_events), §9 and §11 Day 5.
Use skills: ecc:fastapi-patterns, ecc:frontend-patterns, ecc:security-review.
- Exception inbox ranked by ₹ at risk; the invoice page shows PO / receipt / invoice side by side, with the failed rules in plain English.
- Approve / reject / request correction, with a reason. Server-side SoD: requester self-approval 403, uploader approval 403, over-limit 403.
- Audit: same-transaction writes, a per-invoice hash chain, and a "Verify chain" endpoint.
- Audit page: timeline per invoice.
Tests: all the §11 Day 5 tests.
Done when: I can log in as each role and see the right buttons allowed or blocked.
Finish: PROGRESS.md, commit "step 8", reply ≤10 lines.
```

---

## Step 9 — Purchase requests, Control Graph, Trust page, design polish

`/model sonnet` · **Skills:** `ecc:frontend-patterns`, `gstack-design-review`

```
STEP 9 — Requests + Control Graph + Trust page. Read CLAUDE.md, docs/PROGRESS.md, docs/BRAND.md, BUILD_PLAN §1, §2 and §13.
Use skills: ecc:frontend-patterns, then gstack-design-review for a polish pass.
- Purchase request form → approval (SoD applies) → link to an ERP PO number.
- Control Graph page: request → approval → PO → receipt → invoice → match → decision → ERP draft, clickable, per invoice.
- Trust page: the wording from §13 "Say" (AI may be processed outside India), what is read-only, who approved what.
- Consistent brand styling; empty states; loading states. No new features beyond these.
Done when: the full click-path works at localhost:3000 and gstack-design-review has no high-severity items left.
Finish: PROGRESS.md, commit "step 9", reply ≤10 lines, including screenshots or paths of the key pages.
```

---

## Step 10 — Connect the real ERPNext (start the 14-day trial now)

**By hand first:**
- Sign up at frappe.io/cloud → ERPNext trial → create company "Orrfin Demo Pvt Ltd" (India, INR).
- Settings → Accounts Settings → tick **Check Supplier Invoice Number Uniqueness**.
- Your user → API Access → **Generate Keys** → keep the key and secret safe (not in chat).

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `debug-issue`

```
STEP 10 — Live ERPNext read. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2 and §8 (setup part only).
Use skills: ecc:api-connector-builder, debug-issue.
- LiveErpnextAdapter using token auth from env vars ERPNEXT_URL, ERPNEXT_API_KEY and ERPNEXT_API_SECRET (tell me where to put them locally; never commit them).
- A seed script that creates the Step 4 fixture data in ERPNext through the API (vendors, items, POs submitted, receipts).
- A config switch: ERP_MODE=fake|live.
- Record the real response shapes and update the contract tests.
Done when: with ERP_MODE=live, "Sync from ERP" shows ERPNext's POs in Orrfin.
Finish: PROGRESS.md, commit "step 10", reply ≤10 lines, including what I must click in ERPNext.
```

---

## Step 11 — Write draft bills into ERPNext exactly once

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:python-testing`

```
STEP 11 — Outbox write-back. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 in full.
Use skills: ecc:tdd-workflow, ecc:python-testing.
Implement the §8 protocol exactly: erp_outbox states, lookup by supplier + bill_no before any retry,
remarks tag orrfin:<key>, docstatus 0 (draft).
Tests first, including the failure test: the POST succeeds, then the adapter raises a timeout → the retry does a lookup →
exactly one Purchase Invoice exists and the row ends CONFIRMED. Also: a validation error → FAILED, shown in the UI.
UI: the invoice page shows ERP sync status and a "Retry sync" button.
Done when: tests pass, and approving a clean invoice creates exactly one draft in ERPNext (check the ERPNext UI).
Finish: PROGRESS.md, commit "step 11", reply ≤10 lines.
```

---

## Step 12 — Put it on AWS (public demo link)

**By hand first:** BUILD_PLAN §10 **B, C, E**: S3 bucket, RDS database, EC2 server, Elastic IP, DNS.

`/model sonnet` · **Skills:** `ecc:deployment-patterns`, `ecc:docker-patterns`

```
STEP 12 — Deploy. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §9 (IAM) and §10 E–F.
Use skills: ecc:deployment-patterns, ecc:docker-patterns.
- S3 implementation of FileStore; production docker-compose (api, worker, web, caddy); infra/deploy.sh (git tag → build → migrate → up).
- Generate the exact inline IAM policy JSON for my bucket and secrets (ask me for the ARNs).
- Secrets read from Secrets Manager at startup; nothing in the repo.
- Give me numbered, click-by-click steps to run deploy.sh via Session Manager.
Done when: https://<my domain or ip.sslip.io> shows the login page and the full flow works there.
Finish: PROGRESS.md, commit and tag "demo-1", reply ≤12 lines.
```

---

## Step 13 — Final review, QA and rehearsal

`/model sonnet` · **Skills:** `ecc:security-review`, `gstack-qa`

```
STEP 13 — Pre-demo check. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §11 Day 7, §12 and §13.
Use skills: ecc:security-review, then gstack-qa on the public URL.
- Security review of auth, SoD, IAM, secrets, uploads. Fix only high and critical findings.
- QA the full §13 demo script end to end; fix blockers only.
- Confirm RDS automated backups are on.
- Write docs/DEMO_SCRIPT.md: click-by-click for my 10-minute pitch, with the exact demo file to use at each step.
Done when: the demo runs cleanly twice in a row.
Finish: PROGRESS.md, tag "demo-final", reply ≤12 lines.
```

---

## Reusable prompts

**VERIFY** (run after every step, in a new session, `/model sonnet`):
```
VERIFY STEP <n>. Read CLAUDE.md, docs/PROGRESS.md, and the "Done when" line of Step <n> in docs/PROMPTS.md.
Use skills: review-changes, plus ecc:python-review (backend) or ecc:react-review (frontend).
Run all tests, start the app with scripts/dev.ps1, check every "Done when" item, and review the changes from the last commit.
Fix only real failures. Reply with a pass/fail table and ≤5 lines of notes. Append the result to PROGRESS.md.
```

**RESUME** (if a step was interrupted):
```
RESUME. Read CLAUDE.md and docs/PROGRESS.md. Run `git status` and `git log -3`.
Tell me in ≤5 lines where Step <n> stopped, then finish it using the same skills listed for that step in docs/PROMPTS.md.
```

**FIX** (when something on screen is wrong):
```
FIX: <describe what you see, e.g. "the Sync button shows an error">. Use skill: debug-issue.
Read CLAUDE.md and docs/PROGRESS.md only. Find the root cause, fix it, add a test that would have caught it,
and reply in ≤8 lines.
```

**EXPLAIN** (when you want to understand what was built, as a flowchart):
```
EXPLAIN <part, e.g. "the matching engine">. Use skill: explore-codebase.
Give me a plain-English explanation and one simple flowchart. No code changes. ≤25 lines.
```
