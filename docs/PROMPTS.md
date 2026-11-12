# Orrfin Build: Step-by-Step Prompts

Copy one prompt at a time into Claude Code. Each prompt builds one small, testable piece and ends with something you can **see on your laptop**.

*(v2.1, 29 Sep: added Step 5 "Intake-to-procure" and the "Draft POs" step. v2.2, 5 Oct: added ERP research (11), the multi-ERP plug (12) and five connector steps (16–20); later steps renumbered. See BUILD_PLAN "v2.1/v2.2 changes" and docs/ERP_CONNECTORS.md.)*

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
| The app | http://localhost:3000 (or :3001 if you start with `-WebPort 3001`) |
| The API and its interactive docs | http://localhost:8000/docs |
| The ERPNext demo system (from Step 13) | your Frappe Cloud URL |
| The Connectors page (from Step 12) | http://localhost:3000/connectors |

**Starting and stopping everything:** run `.\scripts\dev.ps1` in the VS Code terminal to start everything, and `.\scripts\dev.ps1 -Stop` to stop it. If another project uses port 3000, add `-WebPort 3001`.

**The steps at a glance:**

| # | Step | Workflow |
|---|---|---|
| 1 | Skeleton ✅ | foundation |
| 2 | Bedrock spike (AI reads an invoice) | invoice |
| 3 | Database, login and roles | foundation |
| 4 | Fake ERPNext: vendors, POs, receipts | P2P |
| 5 | **Intake-to-procure** (new) | P2P |
| 6 | Test invoices + answer key | invoice |
| 7 | Upload + AI extraction | invoice |
| 8 | Matching engine | invoice |
| 9 | Exception inbox, approvals, audit | invoice |
| 10 | Control Graph, Trust page, polish | both |
| 11 | **ERP research** ✅ (new) | ERP |
| 12 | **Multi-ERP plug + Connectors page** (new) | ERP |
| 13 | Live ERPNext read | both |
| 14 | Draft bills into the ERP (outbox) | invoice |
| 15 | Draft POs into the ERP | P2P |
| 16 | **Tally (live) + BUSY (sim)** (new) | ERP |
| 17 | **Dynamics Business Central (live) + F&O (sim)** (new) | ERP |
| 18 | **SAP S/4HANA (sandbox) + Business One (sim)** (new) | ERP |
| 19 | **Oracle Fusion + NetSuite (sim)** (new) | ERP |
| 20 | **Zoho Books + Odoo (live)** (new) | ERP |
| 21 | Deploy to AWS | both |
| 22 | Final review and rehearsal | both |

If time runs short, cut Step 19 and the simulated half of Steps 16–18 first (BUILD_PLAN §11 cut order). Keep at least one SAP, one Oracle and one Microsoft card.

Step 2 needs Bedrock access. If that is still pending, do Steps 3–5 first; they need no AI.

---

## Step 0 — Things you do by hand (no Claude, no credits)

Do these once, in order. Tick each one off.

- [x] **Install Docker Desktop:** go to docker.com → Download for Windows → run the installer → keep "Use WSL 2" ticked → restart the PC → open Docker Desktop once and wait until it says "Engine running".
- [ ] **Create an AWS account and secure it:** follow BUILD_PLAN §10 **A** (MFA, the `orrfin-admin` user, a $50 budget, the Mumbai region).
- [ ] **Turn on Claude in Bedrock:** BUILD_PLAN §10 **D**, steps 1–2. Enable Anthropic Claude in the Model catalog and try one message in the Playground. *(Pending since 29 Sep.)*
- [ ] **Create a laptop-only AI key** (so the app on your laptop can call Bedrock):
  1. IAM → Users → **Create user** `orrfin-dev-laptop`. Do **not** tick console access.
  2. Permissions → **Attach policies directly** → `AmazonBedrockLimitedAccess`. If it isn't listed, choose Create policy and allow only `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`.
  3. Open the user → **Security credentials** → **Create access key** → choose "Local code" → download the `.csv`.
  4. Install the AWS CLI (search "AWS CLI install Windows", then run the MSI).
  5. In a terminal, run `aws configure`. Paste the two keys from the `.csv`, set the region to `ap-south-1`, and set the output to `json`.
  6. **Never paste these keys into chat or into any project file.**
- [ ] **Create a free GitHub account**, and a **private** repository named `orrfin`.
- [x] **Paste your colours** into `docs/BRAND.md`.
- [ ] **Confirm the approval tiers and categories** in BUILD_PLAN §9 and §14 Q7 (before Step 5).
- [ ] **Recommended, saves credits:** tell Claude "turn off GateGuard's routine checks". It currently makes Claude explain every command twice.

---

## Step 1 — Project skeleton you can open in the browser ✅ done 29 Sep

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
- Alembic migration for every table in §5 (including the v2.1 tables: categories, approval_policies, request_lines,
  and the extended purchase_requests, request_approvals and erp_outbox), with org_id, NUMERIC money,
  and the audit_events grants (app role: INSERT/SELECT only).
- Email + password login (argon2), session cookie, roles (requester, buyer, approver, finance, admin), approval_limit, manager_id.
- Seed script: 1 org; 5 users (requester whose manager is the approver, buyer, approver, finance, admin);
  3 categories (IT hardware, Office supplies, Professional services) each owned by the buyer;
  the 3 approval tiers from §9. Put the demo passwords in the README.
- Frontend: a login page in brand colours, and a logged-in shell with navigation (Inbox, Requests, Invoices, POs, Audit).
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

## Step 5 — Intake-to-procure: request, routing and approval chain (new in v2.1)

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:fastapi-patterns`

```
STEP 5 — Intake-to-procure. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §1, §2, §5 (request tables) and §9 (approval chain, routing, SoD).
Use skills: ecc:tdd-workflow, ecc:fastapi-patterns.
Tests FIRST for every rule in §9 and the M2 acceptance tests in §11; then implement, in the procurement module.
- Intake form (requester): category, title, justification, cost centre, needed-by date, lines (description, qty, estimated rate),
  optional suggested vendor. Amount = sum of lines, Decimal only.
- Routing: on submit, assign to the category's buyer; no buyer → admin queue. Buyer work queue: set vendor (from synced vendors),
  item codes and rates, then "Send for approval".
- Approval chain from approval_policies: steps in order, server-side SoD (self-approval, buyer approval, same person twice,
  out of order, over limit), approve / reject / return with reason. Amount change restarts the chain.
- Every status change writes its audit event in the same transaction.
- UI: "New request" form; My requests; Buyer queue; Approvals inbox; a request page with a status timeline
  (submitted → with buyer → step 1 → step 2 → approved). Approved requests show "Ready for PO" (the PO itself is drafted in Step 15).
Done when: tests pass, and I can log in as requester → buyer → approver → finance and walk a ₹2,40,000 laptop request to "approved",
and see the requester blocked from approving it.
Finish: PROGRESS.md, commit "step 5: intake-to-procure", reply ≤12 lines.
```

---

## Step 6 — Test invoices and an answer key

`/model sonnet` · **Skills:** `anthropic-skills:pdf`, `ecc:eval-harness`

```
STEP 6 — Synthetic invoices + eval set. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §6 and §7 (evaluation set).
Use skills: anthropic-skills:pdf, ecc:eval-harness.
Create 12 synthetic invoice PDFs in evals/extraction/, each with a ground-truth JSON, tied to the Step 4 POs:
clean match; 7% price variance; over-receipt quantity; partial receipt + second invoice; duplicate number; the same file twice;
bad GSTIN; IGST where CGST+SGST applies; vendor mismatch; closed PO; unpaired line; prompt-injection text inside the PDF.
Add docs/DEMO_DATA.md: a table of which file demonstrates what.
Done when: 12 PDFs + 12 JSON files exist and open correctly.
Finish: PROGRESS.md, commit "step 6", reply ≤8 lines.
```

---

## Step 7 — Upload an invoice and let the AI read it

`/model sonnet` · **Skills:** `claude-api`, `ecc:regex-vs-llm-structured-text`, `ecc:eval-harness`

```
STEP 7 — Extraction pipeline. Read CLAUDE.md, docs/PROGRESS.md, docs/spikes.md, BUILD_PLAN §7.
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
Finish: PROGRESS.md, commit "step 7", reply ≤12 lines, including the accuracy numbers.
```

---

## Step 8 — The matching engine (the heart of the product)

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:python-testing`

```
STEP 8 — Matching engine. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 (duplicate key) and §6 in full.
Use skills: ecc:tdd-workflow, ecc:python-testing.
Write the tests FIRST for every rule in §6 and the ≥14 scenarios in §11 M4; then implement.
- The matching module is pure: no DB, HTTP or AI imports. Decimal only; ROUND_HALF_UP; tolerances in one config object;
  RULE_SET_VERSION stored with every result.
- Cumulative quantity uses invoiced_to_date. Line pairing follows the §6 order; ambiguous → LINE_UNPAIRED.
- amount_at_risk and a risk score from fixed weights.
- Explanation: Claude receives only the rule_results JSON (never document text) and returns plain English.
- Wire it up: after review confirmation → match job → match_results + audit.
Done when: all tests pass; uploading each of the 12 eval PDFs gives the outcome listed in DEMO_DATA.md.
Finish: PROGRESS.md, commit "step 8", reply ≤12 lines, with a pass/fail table.
```

---

## Step 9 — Exception inbox, invoice approvals, segregation of duties, audit trail

`/model sonnet` · **Skills:** `ecc:fastapi-patterns`, `ecc:frontend-patterns`, `ecc:security-review`

```
STEP 9 — Invoice review + controls. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 (audit_events), §9 and §11 M5.
Use skills: ecc:fastapi-patterns, ecc:frontend-patterns, ecc:security-review.
- Exception inbox ranked by ₹ at risk; the invoice page shows PO / receipt / invoice side by side, with the failed rules in plain English.
- Approve / reject / request correction, with a reason. Server-side SoD: uploader approval 403, over-limit 403.
- Audit: same-transaction writes, a per-entity hash chain (invoices and requests), and a "Verify chain" endpoint.
- Audit page: timeline per invoice and per request.
Tests: all the §11 M5 tests.
Done when: I can log in as each role and see the right buttons allowed or blocked.
Finish: PROGRESS.md, commit "step 9", reply ≤10 lines.
```

---

## Step 10 — Control Graph, Trust page, design polish

`/model sonnet` · **Skills:** `ecc:frontend-patterns`, `gstack-design-review`

```
STEP 10 — Control Graph + Trust page. Read CLAUDE.md, docs/PROGRESS.md, docs/BRAND.md, BUILD_PLAN §1, §2 and §13.
Use skills: ecc:frontend-patterns, then gstack-design-review for a polish pass.
- Control Graph page: intake request → approval steps → PO → receipt → invoice → match → decision → ERP draft, clickable,
  per request and per invoice.
- Trust page: the wording from §13 "Say" (AI may be processed outside India), what is read-only, what is draft-only, who approved what.
- Consistent brand styling; empty states; loading states. No new features beyond these.
Done when: the full click-path works at localhost:3000 and gstack-design-review has no high-severity items left.
Finish: PROGRESS.md, commit "step 10", reply ≤10 lines, including screenshots or paths of the key pages.
```

---

## Step 11 — ERP research: which ERPs, how to reach each one ✅ done 5 Oct

Output: `docs/ERP_CONNECTORS.md`. It covers:
- the catalogue of 11 ERPs with a Live/Sandbox/Simulated label for each;
- what each Orrfin record is called in each ERP;
- the per-ERP "draft" and lookup key for §8;
- gotchas;
- the sign-ups you need, with source links.

Facts marked "(unverified)" are checked in the step that builds that connector.

---

## Step 12 — The multi-ERP plug (one port, many ERPs) (new in v2.2)

`/model opus` · **Skills:** `ecc:hexagonal-architecture`, `ecc:database-migrations`

```
STEP 12 — Multi-ERP plug. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2, §4 (connector rules), §5 (erp_connections) and §8 (per-ERP table),
and docs/ERP_CONNECTORS.md §1–§4. Use skills: ecc:hexagonal-architecture, ecc:database-migrations (also explore-codebase to read ports/erp.py,
adapters/erpnext*.py, modules/sync and tests/contract first).
- Extend the ErpAdapter port (app/ports/erp.py): capabilities() (can_read, can_write_bill, can_write_po, label live|sandbox|simulated),
  create_draft_bill, find_bill(vendor_ref, supplier_invoice_no), create_draft_po, find_po(orrfin_key), with Orrfin-side DraftBill/DraftPo models
  and clear result/exception types (Created, Rejected=validation error, Unknown=timeout/5xx). ERPNext implements them against its fixtures for now.
- app/adapters/registry.py: get_adapter(connection) picks the adapter by erp_connections.system + mode (fake|live). Only sync calls it.
- Additive migration: erp_connections table; erp_connection_id on vendors, purchase_orders, goods_receipts, erp_outbox; uniqueness becomes
  (org_id, erp_connection_id, erp_ref). Backfill: one "ERPNext · simulated" connection per org, active. seed_demo creates one row per catalogue ERP
  (inactive except ERPNext).
- One canonical demo dataset (the current 5 vendors / 8 POs / 8 receipts) + a renderer interface so each connector step only adds a
  "render to <ERP> format" function. Move make_erpnext_fixtures.py onto it.
- Shared contract suite tests/contract/test_erp_adapter_contract.py, parametrized over every registered adapter: same vendors, POs (lines, Decimal
  money, GST %), receipts; drafts and lookups behave per capabilities(); a sandbox adapter refuses writes with a clear error.
- UI: /connectors page (admin): a card per catalogue ERP with segment, logo-free name, Live/Sandbox/Simulated badge (colours from BRAND.md), status,
  "Make active" button (audited). Simulated cards say "Built to <ERP>'s published API. Not connected to a live system."
Tests: all existing tests still pass; contract suite green for ERPNext; switching connection + syncing twice keeps row counts; two connections with
the same erp_ref don't collide; making a connection active writes an audit event; non-admin → 403.
Done when: /connectors shows the catalogue with badges, and Sync still shows the ERPNext POs.
Finish: update docs/adr/0004-multi-erp-connectors.md if the build changed any decision, ARCHITECTURE.md, PROGRESS.md, commit "step 12", reply ≤10 lines.
```

---

## Step 13 — Connect the real ERPNext (start the 14-day trial now)

**By hand first:**
- Sign up at frappe.io/cloud → ERPNext trial → create company "Orrfin Demo Pvt Ltd" (India, INR).
- Settings → Accounts Settings → tick **Check Supplier Invoice Number Uniqueness**.
- Customize Form → **Purchase Order** → add a field: label "Orrfin Ref", name `orrfin_ref`, type Data, tick **Unique** and **Read Only** → Update. (Stops duplicate draft POs; BUILD_PLAN §8.)
- Your user → API Access → **Generate Keys** → keep the key and secret safe (not in chat).

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `debug-issue`

```
STEP 13 — Live ERPNext read. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2 and §8 (setup parts only), docs/ERP_CONNECTORS.md (ERPNext rows).
Use skills: ecc:api-connector-builder, debug-issue.
- LiveErpnextAdapter (implements the Step 12 port) using token auth from env vars ERPNEXT_URL, ERPNEXT_API_KEY and ERPNEXT_API_SECRET
  (tell me where to put them locally; never commit them). Registered as erpnext + mode live; the connection's label becomes "live".
- A seed script that creates the canonical demo data in ERPNext through the API (vendors, items, POs submitted, receipts).
- Check that the orrfin_ref custom field exists on Purchase Order; fail with a clear message if not.
- Record the real response shapes and update the contract tests (the shared suite must pass for both fake and live-recorded fixtures).
Done when: with the ERPNext connection set to live, "Sync from ERP" shows ERPNext's POs in Orrfin.
Finish: PROGRESS.md, commit "step 13", reply ≤10 lines, including what I must click in ERPNext.
```

---

## Step 14 — Write draft bills into the ERP exactly once

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:python-testing`

```
STEP 14 — Outbox write-back (bills). Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 in full (incl. the v2.2 per-ERP table).
Use skills: ecc:tdd-workflow, ecc:python-testing.
Implement the §8 protocol exactly, as a generic outbox (doc_type, erp_connection_id) that only calls the port (create_draft_bill / find_bill),
so Step 15 and every later connector reuse it unchanged. ERPNext: lookup by supplier + bill_no before any retry, remarks tag orrfin:<key>,
docstatus 0 (draft). If the active connection can't write bills (capabilities), the approve button explains why and nothing is queued.
Tests first, including the failure test: the POST succeeds, then the adapter raises a timeout → the retry does a lookup →
exactly one Purchase Invoice exists and the row ends CONFIRMED. Also: a validation error → FAILED, shown in the UI.
Make the failure test a reusable fixture so Steps 16–20 run it for each adapter.
UI: the invoice page shows ERP sync status (with the ERP's name) and a "Retry sync" button.
Done when: tests pass, and approving a clean invoice creates exactly one draft in ERPNext (check the ERPNext UI).
Finish: PROGRESS.md, commit "step 14", reply ≤10 lines.
```

---

## Step 15 — Draft POs into the ERP exactly once

`/model opus` · **Skills:** `ecc:tdd-workflow`, `ecc:python-testing`

```
STEP 15 — Draft PO write-back. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2 (PO row), §5 (erp_outbox) and §8 "Draft Purchase Orders" + per-ERP table.
Use skills: ecc:tdd-workflow, ecc:python-testing.
Reuse the Step 14 outbox with doc_type = purchase_order (port: create_draft_po / find_po):
- The final approval step creates the outbox row + job + audit event in the same transaction as status = approved.
- ERPNext: push a draft Purchase Order (docstatus 0) with supplier, schedule_date, approved lines and orrfin_ref = the key.
- UNKNOWN → find_po(orrfin_key) before any retry.
- CONFIRMED → request status po_drafted; the next pull sync links the submitted PO (origin = orrfin) → po_open.
Tests first: the POST succeeds then times out → the retry looks up → exactly one PO, row CONFIRMED; a validation error → FAILED shown on the request;
the approval + outbox row are atomic (no outbox row if the approval fails). Reusable per-adapter fixture, as in Step 14.
UI: the request page shows PO status (drafting / drafted as PUR-ORD-xxxx / open) and "Retry sync".
Done when: tests pass; approving the laptop request creates exactly one draft PO in ERPNext; after I submit it in ERPNext and click Sync, the request shows "PO open".
Finish: PROGRESS.md, commit "step 15", reply ≤10 lines, including what I must click in ERPNext.
```

---

## Step 16 — Tally Prime (live) + BUSY (simulated) (new in v2.2)

**By hand first:**
1. Go to tallysolutions.com → Download TallyPrime → install it.
2. Open TallyPrime → choose **Work in Educational Mode** (free).
3. Create company "Orrfin Demo Pvt Ltd" (India, GST on).
4. Press **F1 (Help) → Settings → Connectivity** → set "TallyPrime acts as" to **Both**, port **9000** → save. (If the menu differs, tell Claude what you see.)
5. Leave TallyPrime open while Claude works.

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `ecc:regex-vs-llm-structured-text`

```
STEP 16 — Tally + BUSY connectors. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 (per-ERP table), docs/ERP_CONNECTORS.md (Tally, BUSY rows + §5).
Use skills: ecc:api-connector-builder, ecc:regex-vs-llm-structured-text (parse Tally XML with a real XML parser, never regex or AI).
First verify every Tally "(unverified)" fact in ERP_CONNECTORS.md against help.tallysolutions.com (Educational-mode dates, ISOPTIONAL, REFERENCE tag,
HTTP-server menu path) and update the file.
- TallyAdapter (mode live: POST XML envelopes to TALLY_URL, default http://localhost:9000; mode fake: recorded XML fixtures).
  Vendors = ledgers under Sundry Creditors (GSTIN from the ledger's GST details); POs = Purchase Order vouchers; receipts = Receipt Note vouchers.
  Draft bill = Optional Purchase voucher; draft PO = Optional Purchase Order voucher; lookups per §8 table. Money as Decimal; Tally's signed amounts handled.
- A seed script that loads the canonical dataset into my Tally company over XML (dates allowed in Educational mode).
- BusyAdapter (simulated, file-based): renders the canonical dataset to BUSY's XML import format; "draft" = an import file a human imports.
- Both join the shared contract suite and the Step 14/15 failure-injection fixtures.
Done when: with Tally active, Sync shows my Tally POs in Orrfin; approving a clean invoice creates exactly one Optional Purchase voucher in Tally
(I check Display More Reports → Exception Reports → Optional Vouchers); /connectors shows Tally "Live" and BUSY "Simulated".
Finish: ERP_CONNECTORS.md updated, PROGRESS.md, commit "step 16", reply ≤10 lines, including what I must click in Tally.
```

---

## Step 17 — Microsoft Dynamics 365: Business Central (live) + Finance & Operations (simulated) (new in v2.2)

**By hand first** (start the 30-day trial only now):
1. You need a **work email** (e.g. you@orrfin.ai); Gmail is refused. No work email? Start a Microsoft 365 Business trial first; it gives you one.
2. Go to dynamics.microsoft.com → Business Central → **Try for free** → sign up with the work email → choose country **India**.
3. Go to entra.microsoft.com → App registrations → **New registration** "Orrfin" → copy the Application (client) ID and Directory (tenant) ID → Certificates & secrets → **New client secret** → copy the value (keep it out of chat).
4. API permissions → Add → **Dynamics 365 Business Central** → Application permissions → `API.ReadWrite.All` → **Grant admin consent**.
5. In Business Central, search "Microsoft Entra Applications" → New → paste the client ID → State Enabled → add permission set **D365 BUS FULL ACCESS**.

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `ecc:hexagonal-architecture`

```
STEP 17 — Microsoft connectors. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 (per-ERP table), docs/ERP_CONNECTORS.md (Business Central, F&O rows).
Use skills: ecc:api-connector-builder, ecc:hexagonal-architecture.
First verify the BC and F&O "(unverified)" facts against learn.microsoft.com (purchaseReceipts resource, PO reference field, duplicate check) and update the file.
- BusinessCentralAdapter: OAuth client credentials (env BC_TENANT_ID, BC_CLIENT_ID, BC_CLIENT_SECRET, BC_ENVIRONMENT, BC_COMPANY_ID; tell me where
  to put them; never commit). API v2.0: vendors, purchaseOrders, purchaseReceipts, purchaseInvoices (unposted = draft). Lookups per §8.
- A seed script that loads the canonical dataset into my BC company (vendors with GSTIN, items, POs, receipts).
- DynamicsFoAdapter (simulated): fixtures in the OData data-entity shapes (VendorsV2, PurchaseOrderHeadersV2/LinesV2, product receipts,
  VendorInvoiceHeaders); draft = pending vendor invoice.
- Both join the shared contract suite and the failure-injection fixtures.
Done when: with BC active, Sync shows my BC POs; approving a clean invoice creates exactly one unposted purchase invoice in BC (Purchasing → Purchase Invoices);
/connectors shows BC "Live" and F&O "Simulated".
Finish: ERP_CONNECTORS.md updated, PROGRESS.md, commit "step 17", reply ≤10 lines, including what I must click in BC.
```

---

## Step 18 — SAP: S/4HANA (sandbox read + simulated write) + Business One (simulated) (new in v2.2)

**By hand first:** go to **api.sap.com** → Log on (create a free SAP account) → open any S/4HANA Cloud API → click **Show API Key** → copy it (keep it out of chat).

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `ecc:hexagonal-architecture`

```
STEP 18 — SAP connectors. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §2 (PO row) and §8 (per-ERP table), docs/ERP_CONNECTORS.md (SAP rows).
Use skills: ecc:api-connector-builder, ecc:hexagonal-architecture.
First check on api.sap.com which S/4HANA Cloud APIs still have a live sandbox (supplier/business partner, purchase order V2 or its V4 successor,
material document, supplier invoice, purchase requisition) and how a supplier invoice is parked via the API; update ERP_CONNECTORS.md.
- SapS4Adapter, two modes in one adapter:
  sandbox (env SAP_API_KEY, header APIKey, sandbox base URL): reads SAP's sample suppliers, POs and goods receipts; capabilities = read only.
  simulated: fixtures in the same OData shapes rendered from the canonical dataset; draft bill = parked supplier invoice; draft PO = purchase
  requisition (BUILD_PLAN §8); lookups per §8. The UI says "write-back simulated" next to SAP.
- SapB1Adapter (simulated): Service Layer shapes (BusinessPartners, PurchaseOrders, PurchaseDeliveryNotes, PurchaseInvoices, Drafts).
- Map SAP sample POs that lack GSTIN gracefully (vendor gstin None → the matching engine's VENDOR rules still run on Orrfin's side).
- Both join the shared contract suite; the simulated modes also run the failure-injection fixtures.
Done when: with SAP active (sandbox), Sync shows real SAP sandbox POs in Orrfin; /connectors shows SAP S/4HANA "Sandbox · write simulated" and SAP Business One "Simulated".
Finish: ERP_CONNECTORS.md updated, PROGRESS.md, commit "step 18", reply ≤10 lines.
```

---

## Step 19 — Oracle: Fusion Cloud ERP + NetSuite (simulated) (new in v2.2)

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `ecc:hexagonal-architecture`

```
STEP 19 — Oracle connectors. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 (per-ERP table), docs/ERP_CONNECTORS.md (Oracle Fusion, NetSuite rows).
Use skills: ecc:api-connector-builder, ecc:hexagonal-architecture.
First verify the Oracle "(unverified)" facts on docs.oracle.com (receipt read resource, draftPurchaseOrders, invoice validation state) and the NetSuite
externalId upsert, and update ERP_CONNECTORS.md.
- OracleFusionAdapter (simulated): fixtures shaped like /fscmRestApi/resources/11.13.18.05/ suppliers, purchaseOrders, receipts, invoices
  (items[] + links paging); draft bill = unvalidated Payables invoice; lookups per §8 (q= filter on Supplier + InvoiceNumber).
- NetSuiteAdapter (simulated): SuiteTalk REST shapes (vendor, purchaseOrder, itemReceipt, vendorBill); writes use PUT .../eid:<idempotency key>,
  so the adapter shows native idempotency (lookup = GET by eid).
- Both join the shared contract suite and the failure-injection fixtures.
Done when: tests pass; with each active, Sync shows the canonical POs; /connectors shows both "Simulated".
Finish: ERP_CONNECTORS.md updated, PROGRESS.md, commit "step 19", reply ≤10 lines.
```

---

## Step 20 — Zoho Books (live) + Odoo (live, on your laptop) (new in v2.2)

**By hand first:**
1. Go to zoho.com/in/books → **Sign up free** → India → create organisation "Orrfin Demo Pvt Ltd" (GST registered).
2. Go to **api-console.zoho.in** → Add Client → **Self Client** → copy the Client ID and Client Secret (keep them out of chat). Claude will tell you which scope to paste to get a code.
3. Odoo: nothing to do. Claude starts it in Docker.

`/model sonnet` · **Skills:** `ecc:api-connector-builder`, `ecc:docker-patterns`

```
STEP 20 — Zoho Books + Odoo. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §8 (per-ERP table), docs/ERP_CONNECTORS.md (Zoho, Odoo rows + §5).
Use skills: ecc:api-connector-builder, ecc:docker-patterns.
First verify the Zoho "(unverified)" facts (draft bills, purchase receives on the Books API, duplicate bill warning) and update ERP_CONNECTORS.md.
- ZohoBooksAdapter: OAuth via accounts.zoho.in (env ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID; walk me through getting the
  refresh token; never commit); base https://www.zohoapis.in/books/v3; vendors (contacts), purchaseorders, receipts per the verified API, bills (draft).
- OdooAdapter: add an `odoo` service (Odoo 19 Community + its own Postgres) to infra/docker-compose.yml under a profile so it only starts when asked;
  JSON-2 API with a Bearer API key; res.partner, purchase.order, stock.picking (incoming), account.move in_invoice (draft). Install the Purchase,
  Inventory and Invoicing apps by script.
- Seed scripts that load the canonical dataset into both.
- Both join the shared contract suite and the failure-injection fixtures.
Done when: with each active, Sync shows its POs; approving a clean invoice creates exactly one draft bill in Zoho Books and one in Odoo (I check both UIs);
/connectors shows both "Live".
Finish: ERP_CONNECTORS.md updated, README (how to start Odoo), PROGRESS.md, commit "step 20", reply ≤10 lines, including what I must click.
```

---

## Step 21 — Control dashboard + Rules page (new in v2.3)

`/model sonnet` · **Skills:** `ecc:fastapi-patterns`, `ecc:frontend-patterns`

```
STEP 21 — Dashboard + Rules. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5, §6, §9 and §11 M6c.
Use skills: ecc:fastapi-patterns, ecc:frontend-patterns (dataviz guidance for bars).
- modules/insights/: GET /insights/summary?period=month|quarter|all: open requests by step, average + median approval time, invoices on hold
  + ₹ at risk, first-pass match rate, exceptions by rule code, slowest approvers, spend by category / cost centre / top vendors, ERP draft
  states, extraction quality. Decimal money as strings; org-scoped; requesters see only their own; buyers their categories.
- /home becomes the landing page. Plain HTML/SVG bars, brand colours, no new chart package.
- /rules: IF/THEN cards for approval tiers, category → buyer, SoD (read-only), matching rules + tolerances + RULE_SET_VERSION (read-only).
  Admin edits tiers (from ₹0, no gaps/overlaps, last open-ended) and category buyers; edit + audit in one transaction; old tiers deactivated.
  Edits apply to new approval chains only; the page says so.
Done when: insights numbers tested on a fixed dataset; org A cannot see org B; non-admin edit → 403; bad tiers refused; an in-flight
request keeps its chain while a new one uses the new tier; tsc + lint clean.
Finish: PROGRESS.md, commit "step 21", reply ≤10 lines.
```

---

## Step 22 — Workflows: reminders, exception tasks, category approvals, budgets, WhatsApp preview (new in v2.4)

`/model sonnet` · **Skills:** `ecc:fastapi-patterns`, `ecc:database-migrations`

```
STEP 22 — Workflows. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5, §9 and change rows 29–30.
Use skills: ecc:fastapi-patterns, ecc:database-migrations.
- GET /tasks (derived): approval steps waiting on me with age and "overdue" past org_settings.approval_sla_hours (default 48), exception tasks
  assigned to me, invoices to review. Bell with count in the sidebar. Nudge on an overdue step → audit "nudged"; the task shows who nudged.
- exception_tasks: reviewer asks the requester a question on a held invoice; approve → 409 while open; the assignee answers; the assignee
  can never approve that invoice. Audited.
- categories.extra_approver_id + extra_step_label: an extra named step after the amount tiers (seed "Software & SaaS" → IT security lead).
- budgets per cost centre per quarter: committed + spent, warning on the request page, dashboard tile; editable on /rules. Never blocks.
- WhatsApp preview on each task: the message an approver would get + the normal link (login required). "Preview — not sent".
Done when: tests for overdue, nudge audit, task blocking approval, extra step SoD, budget maths; all earlier tests pass; tsc + lint clean.
Finish: PROGRESS.md, commit "step 22", reply ≤10 lines.
```

---

## Step 23 — Orrfin Assistant: the read-only AI agent (new in v2.3)

`/model sonnet` · **Skills:** `claude-api`, `ecc:hexagonal-architecture`

```
STEP 23 — Assistant. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §4 (assistant rule), §5 (assistant_turns), docs/adr/0005.
Use skills: claude-api, ecc:hexagonal-architecture.
- Port ports/assistant.py; adapters gemini_assistant.py (manual function calling, ≤6 tool rounds, one SDK attempt, 60 s),
  claude_assistant.py (tool use), fake_assistant.py (scripted). Prompts in ai_prompts.py with ASSISTANT_PROMPT_VERSION.
- modules/assistant/: read-only tools run as the logged-in user over existing service code. No writes, no ERP calls, no raw document text.
- POST /assistant/ask: links only to IDs a tool returned; every ₹ figure checked against tool results; 30 questions/hour/user;
  assistant_turns log. AI down → "Assistant unavailable".
- Assistant side panel on every page; suggested questions per role and page. ADR 0007; Trust page section.
Done when: fake-model tests prove scope per tool, dropped unknown links, the ₹ warning, rate limit, outage fallback and a logged turn.
Finish: PROGRESS.md, commit "step 23", reply ≤10 lines.
```

---

## Step 24 — Intake agent, exception notes, AI "what changed" notes, assistant evaluation (new in v2.3/v2.4)

`/model sonnet` · **Skills:** `ecc:eval-harness`, `ecc:tdd-workflow`

```
STEP 24 — Intake agent + AI notes + eval. Read CLAUDE.md, docs/PROGRESS.md, docs/adr/0007.
Use skills: ecc:eval-harness, ecc:tdd-workflow.
- POST /assistant/draft-request: one sentence → a pre-filled request (category, title, justification, needed-by, lines + qty). Rates from
  the last PO price, never AI-guessed. Shows the approval chain and budget effect. Requester submits; audit records drafted_by_ai.
- "Draft a note" on an exception (and for an exception-task question): from rule results; copy only.
- POST /insights/notes: 3–5 "what changed" bullets from computed comparisons only; ₹-checked; template fallback.
- evals/assistant/: ~25 questions, permission cases, an injection invoice; CI with the fake model; run_assistant_eval.py --provider gemini.
Done when: the eval passes in CI; a drafted request still blocks self-approval; notes fall back cleanly without AI.
Finish: PROGRESS.md, commit "step 24", reply ≤10 lines.
```

---

## Step 25 — Simulated payments, payment-risk checks, TDS (new in v2.4)

`/model sonnet` · **Skills:** `ecc:tdd-workflow`, `ecc:security-review`

```
STEP 25 — Payments. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §6b, §6c, §9 and docs/adr/0008.
Use skills: ecc:tdd-workflow (tests first for TDS and risk), ecc:security-review.
- vendor_payment_profiles (PAN, TDS section, bank account, IFSC) with maker-checker: whoever changes bank details cannot verify them.
- tds.py (194C/194J/194Q, thresholds, nearest rupee, 206AA no-PAN rate) and risk.py (block/hold rules), both pure and versioned.
- payment_runs + payment_lines: finance prepares from approved invoices; preparer ≠ approver; invoice approver ≠ payment approver;
  approval limit; blocking risk → cannot submit; holds need a reason.
- Generic NEFT/RTGS bulk CSV; "Send to bank (simulated)" → job bank_settle: UTRs, one seeded failure, a bank statement CSV.
- /payments UI; vendor payment profile + verify; dashboard payment tiles; assistant payment tools.
Done when: TDS and net asserted to the paisa; every SoD 403; bank file total = run total; settle twice = one settlement; no high
security findings.
Finish: PROGRESS.md, commit "step 25", reply ≤10 lines.
```

---

## Step 26 — Bank reconciliation + month-end close cockpit (new in v2.4)

`/model sonnet` · **Skills:** `ecc:tdd-workflow`, `ecc:fastapi-patterns`

```
STEP 26 — Bank + close. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN change row 32, docs/adr/0008.
Use skills: ecc:tdd-workflow, ecc:fastapi-patterns.
- Bank statement CSV import (duplicate file refused); reconcile.py: UTR → matched; amount + date ±3 days + name → suggested (a person
  accepts); else unmatched. /bank page.
- close_periods + /close: live checklist, received-not-invoiced report (CSV), AI "what changed" notes, close with sign-off; a closed month
  refuses invoice and payment approvals dated in it (409) until an admin reopens with a reason.
Done when: the mock bank statement reconciles 100% by UTR end to end; period lock tested; audit row per change.
Finish: PROGRESS.md, commit "step 26", reply ≤10 lines.
```

---

## Step 27 — GSTR-2B ITC matching + photo / handwritten bills (new in v2.4)

`/model sonnet` · **Skills:** `ecc:tdd-workflow`, `ecc:regex-vs-llm-structured-text`

```
STEP 27 — GSTR-2B + photo bills. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §5 duplicate key, §7, change row 34.
Use skills: ecc:tdd-workflow, ecc:regex-vs-llm-structured-text.
- POST /gstr2b (GSTN 2B JSON shape): match by GSTIN + normalised invoice no + fiscal year → matched / amount differs / ITC at risk / not in
  books. /gst page, dashboard "ITC at risk" tile, payment-risk hold for invoices missing from 2B. Matching only, no filing.
- Upload accepts JPEG/PNG photos (magic bytes, ≤10 MB); Extractor.extract(data, mime_type) in every adapter; prompt: never guess an
  unreadable figure. Two synthetic photo invoices in the eval set.
Done when: 2B matching tests pass on the seed fixture; a photo invoice goes upload → extract → confirm → match with the fake extractor.
Finish: PROGRESS.md, commit "step 27", reply ≤10 lines.
```

---

## Step 28 — Put it on AWS (public demo link)

> *(v3.0)* Steps 28 and 29 now run **after Step 40**. The platform steps 30–40 are listed below Step 29.

**By hand first:** BUILD_PLAN §10 **B, C, E**: S3 bucket, RDS database, EC2 server, Elastic IP, DNS.

`/model sonnet` · **Skills:** `ecc:deployment-patterns`, `ecc:docker-patterns`

```
STEP 28 — Deploy. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §9 (IAM) and §10 E–F.
Use skills: ecc:deployment-patterns, ecc:docker-patterns.
- S3 implementation of FileStore; production docker-compose (api, worker, web, caddy); infra/deploy.sh (git tag → build → migrate → up).
- Generate the exact inline IAM policy JSON for my bucket and secrets (ask me for the ARNs). ERP credentials (ERPNext, BC, SAP key, Zoho) go into
  Secrets Manager too. Tally and Odoo stay on the laptop: their cards say "laptop only" on the public URL.
- Secrets read from Secrets Manager at startup; nothing in the repo.
- Give me numbered, click-by-click steps to run deploy.sh via Session Manager.
Done when: https://<my domain or ip.sslip.io> shows the login page and the full flow works there.
Finish: PROGRESS.md, commit and tag "demo-1", reply ≤12 lines.
```

---

## Step 29 — Final review, QA and rehearsal

`/model sonnet` · **Skills:** `ecc:security-review`, `gstack-qa`

```
STEP 29 — Pre-demo check. Read CLAUDE.md, docs/PROGRESS.md, BUILD_PLAN §11 M7, §12 and §13.
Use skills: ecc:security-review, then gstack-qa on the public URL.
- Security review of auth, SoD (requests and invoices), IAM, secrets (incl. every ERP credential), uploads. Fix only high and critical findings.
- QA the full §13 demo script end to end (intake → PO → invoice → bill → Connectors page); fix blockers only.
- Check every connector badge and its wording against §13 "Say / Never say".
- Confirm RDS automated backups are on.
- Write docs/DEMO_SCRIPT.md: click-by-click for my pitch, with the exact demo request and file to use at each step, and which ERP to make active when.
Done when: the demo runs cleanly twice in a row.
Finish: PROGRESS.md, tag "demo-final", reply ≤12 lines.
```

---

# Platform v3.0 (Steps 30–40)

Approved 12 Nov 2026 (BUILD_PLAN v3.0, ADR 0009, ADR 0010). One step per session. Every step: read CLAUDE.md and
docs/PROGRESS.md first; tests before money, permission or retry logic; finish with the full suite, tsc, lint and
build green, a browser walk-through per role, ≤8 lines in PROGRESS.md and a commit.

## Step 30 — Design system + app shell

**Skills:** `frontend-design`, `shadcn`; review with `gstack-design-review`

```
STEP 30 — App shell. Read BUILD_PLAN change 37, §11 M8, docs/BRAND.md.
- Extend frontend/src/styles/tokens.css (type scale, spacing, elevation, status colours); keep the brand colours.
- Shell in app/(app)/layout.tsx: grouped left navigation by product, top bar (entity switcher, search, notifications,
  Ask Orrfin), command palette (Ctrl+K). Shared PageHeader, DataTable, EmptyState, StatusBadge, chart components.
- Move the existing pages into the shell with no behaviour change. Nav items hidden by role are still refused by the API.
Done when: §11 M8.
```

## Step 31 — Platform foundation: entities, currencies, tax regimes, workflow engine, intake forms

**Skills:** `ecc:tdd-workflow`, `ecc:postgres-patterns`

```
STEP 31 — Foundation. Read BUILD_PLAN changes 38–40, §5 (v3.0 rows), §6d, §9 (v3.0), ADR 0010.
- Additive migration: legal_entities, entity_memberships, fx_rates, workflow_*, request_types, form_fields, notifications,
  api_keys, webhook_*; entity_id and currency where needed (existing rows → the org's default entity, INR).
- matching/tax.py: regime in_gst (unchanged behaviour) and ae_vat; CURRENCY_MISMATCH; credit/debit notes as a negative
  invoice linked to the original. Tests first; bump RULE_SET_VERSION.
- modules/workflow_engine: validator, interpreter on the jobs table, immutable versions, simulate. The v2.1 chain is the
  default template; decision_refusal stays the only place SoD is decided.
- modules/intake_forms, modules/notifications (in-app, email to console locally, signed webhooks through security/outbound.py).
- UI: /automation/workflows (visual builder), /settings/forms, /settings/entities.
Done when: §11 M9.
```

## Step 32 — Supplier onboarding, supplier portal, risk orchestration

**Skills:** `ecc:tdd-workflow`, `ecc:security-review`

```
STEP 32 — Suppliers. Read BUILD_PLAN changes 41–42, §2 (v3.0 rows), §6e, §9 supplier portal.
- modules/suppliers: invite (single-use hashed token) → portal sign-up → profile, documents, bank proof → checks → review
  workflow → maker-checker bank verify (reuse payments) → handover; the sync links the ERP vendor back.
- Supplier portal: its own login realm, cookie and routes under /portal; a supplier session reaches nothing else.
- modules/supplier_risk: pure rules.py (blocks, holds, score, level), questionnaire, synthetic sanctions list, review dates;
  critical level holds new POs and payments.
Done when: §11 M10.
```

## Step 33 — Sourcing + AI contract orchestration

**Skills:** `ecc:tdd-workflow`, `claude-api`

```
STEP 33 — Sourcing and contracts. Read BUILD_PLAN changes 43–44, §6f.
- modules/sourcing: RFQ, invites, quotes entered in the portal, pure compare.py (landed cost, score with stored weights),
  human award with snapshot → request → the existing approval chain → draft PO through the outbox. RFQ PDF.
- modules/contracts: upload, AI term extraction with quoted page evidence (same contract as §7: evidence or it is not a
  term), human confirmation, obligations, renewal tasks, rule-based playbook flags. Add an injection contract to the evals.
Done when: §11 M11.
```

## Step 34 — Global payments + vendor cards (simulated)

**Skills:** `ecc:tdd-workflow`, `ecc:hexagonal-architecture`

```
STEP 34 — Money products, simulated. Read ADR 0008, BUILD_PLAN changes 45–46, §6b, §6c.
- ports/payment_provider.py + mock bank: runs per currency and rail, FX from fx_rates (never AI), IBAN/SWIFT/IFSC validators,
  payment-advice PDF. Every Step 25 SoD and risk rule applies per currency.
- ports/card_issuer.py + mock issuer; modules/cards: request-linked virtual card (limit, expiry, merchant lock), simulated
  transactions, matching to the request/invoice, freeze and close. Every screen says "simulated".
Done when: §11 M12.
```

## Step 35 — AI layer: chat home, proposals, workflow-builder agent, superagents, MCP

**Skills:** `claude-api`, `ecc:eval-harness`

```
STEP 35 — AI layer. Read ADR 0007, ADR 0010, BUILD_PLAN change 47, §4 assistant rule.
- /ask chat home. Proposal tools return typed cards (request, RFQ, supplier invite, workflow draft) stored in
  action_proposals (user, payload hash, expiry); the person submits through the normal endpoint, which re-checks everything.
- Workflow-builder agent: chat → definition → validator → diagram + simulation → admin publishes. No publish tool exists.
- Superagents = named tool groups with an agent_runs log. app/mcp_server: the same tools under a per-user API key.
- Evals: 100+ cases (facts, permissions, injection, cross-org, forbidden actions, stale records); facts checked against the
  record they belong to, not only the amount.
Done when: §11 M13.
```

## Step 36 — Eight more connectors + integrations gallery

**Skills:** `ecc:api-connector-builder`, `ecc:hexagonal-architecture`

```
STEP 36 — Connectors. Read docs/ERP_CONNECTORS.md, ADR 0004, ADR 0006, BUILD_PLAN change 48.
- QuickBooks Online, Xero, Sage Intacct, Sage 50/200, Acumatica, Focus X, Marg ERP, TallyPrime UAE VAT mode: for each,
  check the vendor's official API documentation first, then <erp>.py + <erp>_sim.py + registry entry + canonical renderer,
  added to tests/contract/erp_adapters.py and tests/failure/erp_write_cases.py. Mark every unverified fact.
- /integrations gallery: ERPs, webhooks, API keys, MCP, notification channels, each with its label and verification date.
Done when: §11 M14.
```

## Step 37 — Spend insights, generated PDFs, App Studio

**Skills:** `ecc:postgres-patterns`, `dataviz`

```
STEP 37 — Insights, documents, App Studio. Read BUILD_PLAN change 49.
- Spend cube (entity, category, vendor, cost centre, period, currency); commitment, invoiced and paid as separate measures;
  off-contract and no-PO spend; sourcing savings; CSV and PDF export. Deterministic SQL only.
- modules/documents/pdf.py: PO, RFQ, payment advice, audit pack. Tests read each PDF back.
- modules/app_studio: custom object = form + workflow + list view. No customer code runs.
Done when: §11 M15.
```

## Step 38 — Security hardening + attack pass

**Skills:** `security-audit` (full audit mode), `ecc:security-review`

```
STEP 38 — Security. Read BUILD_PLAN §9 (all), §12, change 50.
- Build: TOTP MFA, lockout, session rotation, CSRF tokens, rate limits, security headers and CSP, Postgres row-level
  security on org_id, upload re-validation, dependency audits (pip-audit, npm audit), secret scan, non-root containers.
- Attack every product as an outsider, a supplier, each employee role and another org: object-level access, privilege
  escalation, SoD bypass, mass assignment, injection (SQL, CSV, XML, prompt), SSRF, upload tricks, session and CSRF,
  proposal and outbox replay, API-key and MCP abuse. Each finding: a failing test in backend/tests/security/, the fix, a re-run.
- Write docs/SECURITY_REVIEW.md: what was tried, what was found, what was fixed, what remains for §12.
Done when: §11 M16.
```

## Steps 39–40 — Cleanup, structure and documentation

**Skills:** `refactor-safely`, `ecc:update-docs`

```
STEPS 39–40 — Cleanup. Read ARCHITECTURE.md and the graph's dead-code report.
- Remove a file only after the graph and a text search show no caller. Group adapters per ERP; make every module the same
  shape (router.py, service.py, schemas.py, pure rule files); one docstring per module naming its BUILD_PLAN section.
- Rewrite ARCHITECTURE.md, README.md and CONNECT_ERPS.md to match. Run the full suite after every move.
Done when: §11 M17. Then continue with Step 28.
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
