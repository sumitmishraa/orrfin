# Orrfin

Orrfin is a procurement platform built around the customer's existing ERP. It started as a P2P invoice-matching "Control Gate" (Steps 1-27) and, from plan v3.0, adds supplier onboarding, sourcing, risk, contracts, a workflow engine, spend insights, simulated global payments and vendor cards, and an AI concierge.

**The source of truth is [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) (v3.0).** Read it before any work, and follow its milestones in order (M0 to M6d done; M8 to M17 next; M7 deploy last).

Build step by step with [docs/PROMPTS.md](docs/PROMPTS.md). At the start of every step, read [docs/PROGRESS.md](docs/PROGRESS.md) (the handoff log); at the end, append 8 lines or fewer to it. UI colours come from [docs/BRAND.md](docs/BRAND.md).

Status: Steps 1, 3-10 done (to 4 Oct): skeleton; login and roles; fake-ERPNext sync; intake-to-procure; evaluation invoices; upload + extraction; matching engine; invoice review with SoD and audit; Control Graph + Trust page. AI now runs on Google Gemini (`AI_PROVIDER=gemini`, ADR 0005) until Bedrock access is granted; real-AI accuracy waits on the founder's GEMINI_API_KEY in `.env`. Plan v2.2 (5 Oct): multi-ERP connectors; Step 11 (ERP research, [docs/ERP_CONNECTORS.md](docs/ERP_CONNECTORS.md)) done. Steps 12-20 done (13 Oct): multi-ERP plug, encrypted connector keys (ADR 0006), outbox write-back of draft bills/POs, 11 connectors (Live: ERPNext, TallyPrime, Business Central, Zoho Books, Odoo; Sandbox: SAP S/4HANA; Simulated: BUSY, Dynamics F&O, SAP B1, Oracle Fusion, NetSuite). Founder connects accounts with docs/CONNECT_ERPS.md. Plan v2.4 (18 Oct, from the Zip/DualEntry research): Steps 21-27 = dashboard + Rules page; workflows (reminders, exception tasks, category approvals, budgets, WhatsApp preview); read-only AI assistant; intake agent + AI notes; simulated payments + payment risk + TDS; bank reconciliation + month-end close; GSTR-2B ITC matching + photo bills. Steps 21-27 done (19 Oct): all of the above built and tested (simulated payments only, no real money; GSTR-2B matched, never filed). Plan v3.0 (12 Nov, ADR 0009 + 0010): 17-product platform in Steps 30-40 (shell; entities + currencies + tax regimes + workflow engine + intake forms; suppliers + portal + risk; sourcing + contracts; simulated global payments + vendor cards; AI layer + MCP; 8 more connectors; spend insights + PDFs + App Studio; security pass; cleanup). AWS (Step 28) and final review (Step 29) run after Step 40. Steps 31-38 built and Steps 39-40 docs done on branch `platform-v3` (15 Nov): all 17 v3.0 products exist (suppliers + portal + risk, sourcing, contracts, simulated global payments + vendor cards, agents + MCP, 8 more simulated ERPs = 19, spend insights, PDFs, App Studio), plus MFA and row-level security. Open items: docs/SECURITY_REVIEW.md and the per-step notes in docs/PROGRESS.md. Step 41 (16 Nov, ADR 0011): team members + simulated power seats + single-use invite links (`/settings/team`, `/join`), two-step sign-in on the login page, and the GoHighLevel-style UI refresh (navy sidebar, area tabs, shared DataTable). Step 42 (17 Nov, ADR 0012): need-first intake (employee states the need, pasted from WhatsApp/email if needed; manager approves; procurement builds one PO per vendor from approved needs on `/orders`; Finance approves by amount; one ERP draft PO; simulated vendor email + PDF). Next: Step 28 (AWS) and Step 29 (final review). Update this line as milestones complete.

## Non-negotiables

- Synthetic data only. No secrets in the repo.
- No **real** money movement: payments are simulated (bank bulk file + mock bank), never a real bank connection (ADR 0008). No GST filing: GSTR-2B is read and matched only. No ledger posting: Orrfin writes no journals and no ERP payment entries; ERP writes are draft Purchase Invoices and draft POs only, through the outbox protocol (BUILD_PLAN §8).
- *(v3.0)* Global payments and vendor cards are simulated too (mock bank, mock card issuer). The ERP owns the vendor master: Orrfin never creates or edits a vendor in an ERP.
- *(v3.0)* AI may propose a typed card (request, RFQ, supplier invite, workflow draft); a named person submits or publishes it through the normal endpoint. AI never publishes a workflow, awards an RFQ, scores supplier risk or sets an exchange rate. A workflow can add steps but can never switch off a §9 rule.
- AI extracts, explains and drafts; it never acts. Deterministic rules decide the match, payment risk, TDS and bank reconciliation (§6, §6b, §6c). A named human approves, with segregation of duties enforced on the server (§9).
- Money is `NUMERIC(18,2)` / `Decimal`, never float.
- `org_id` goes on every business table.
- Every state change is written in the same transaction as its `audit_events` row.
- Migrations are additive only during demo week.
- Ask before changing BUILD_PLAN sections 2, 5, 6 or 8.

## How to work on every request

1. **Pick skills first.** Before starting any task, choose the one or two most relevant skills from the table below. In the first line of the reply, state which were chosen and why. Use one skill per job; don't stack overlapping skills (for example, ECC review and gstack review together).
2. **Stay in the domain.** Orrfin is P2P, invoice matching, ERP integration and finance controls. Don't add features, tools or abstractions that aren't in `docs/BUILD_PLAN.md`.
3. **Write code for the next developer.**
   - Clear names over clever code.
   - Every module starts with a short docstring saying what it owns and which BUILD_PLAN section it implements.
   - Comments explain *why* (a business rule, a tolerance, a failure mode), not *what*.
   - Keep `docs/ARCHITECTURE.md` and the README current when structure changes.
   - Record significant decisions as short ADRs in `docs/adr/`.
4. **Never install new skills, plugins or MCP servers without the user's approval.** This overrides `find-skills`, which suggests installing globally with `-y`. Search and recommend, then ask.

### Skill routing

| Work | Use |
|---|---|
| Plan or slice a milestone | `ecc:plan`, `ecc:orch-build-mvp`; challenge a plan with `gstack-plan-eng-review` |
| Understand existing code before changing it | `explore-codebase` (code-review-graph) |
| FastAPI / Python backend | `ecc:fastapi-patterns`, `ecc:python-patterns` |
| Database schema, migrations, SQL | `ecc:postgres-patterns`, `ecc:database-migrations` |
| Matching rules and any money logic (tests first) | `ecc:tdd-workflow`, `ecc:python-testing` |
| AI extraction / Claude calls | `claude-api`, `ecc:regex-vs-llm-structured-text`, `ecc:eval-harness` |
| ERP adapter (ERPNext) | `ecc:api-connector-builder`, `ecc:hexagonal-architecture` |
| Next.js UI | `ecc:frontend-patterns`, `ecc:nextjs-turbopack`; visual polish with `gstack-design-review` |
| Docker, EC2, deploy | `ecc:docker-patterns`, `ecc:deployment-patterns` |
| Code review before commit | `review-changes` (code-review-graph) + `ecc:python-review` |
| Security review | `ecc:security-review`; full audit or attack pass with `security-audit` (Cloudflare) plus the focused `testing-*` skills in `.claude/skills/` (`gstack-cso` is unavailable on Windows) |
| Bug investigation | `debug-issue` (code-review-graph) or `gstack-investigate` |
| Browser QA of the demo | `gstack-qa` or `ecc:browser-qa` |
| Docs and architecture notes | `gstack-document-generate`, `ecc:update-docs` |
| Claude Code setup and automation ideas | `claude-automation-recommender` (from the official claude-code-setup plugin; read-only) |
| Looking for a skill that doesn't exist here | `find-skills` (recommend only; see rule 4) |

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Start with the code-review-graph
MCP tools to narrow scope, then read the source.** The graph is cheaper than scanning files and
gives you structural context (callers, dependents, test coverage) that file search cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

### Verify in the source

- Narrow scope with the graph, then read the source. Do not change code from graph output alone.
- For any non-trivial change, read the implementation and the relevant tests before concluding.
- Verify the exact source when touching behavior, database logic, migrations, retries, fallbacks,
  recovery, or compatibility code.
- When the graph and the source disagree, the source wins. The graph may be stale or may not
  model that relationship.
- An empty graph result can mean "not indexed" or "not statically visible", not "does not exist".

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
<!-- /code-review-graph MCP tools -->
