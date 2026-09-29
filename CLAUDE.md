# Orrfin

Orrfin is building a 7-day investor prototype: a P2P invoice-matching "Control Gate" connected to ERPNext.

**The source of truth is [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) (v2.1).** Read it before any work, and follow its milestones in order (M0 to M7).

Build step by step with [docs/PROMPTS.md](docs/PROMPTS.md). At the start of every step, read [docs/PROGRESS.md](docs/PROGRESS.md) (the handoff log); at the end, append 8 lines or fewer to it. UI colours come from [docs/BRAND.md](docs/BRAND.md).

Status: Steps 1, 3, 4, 5, 6 done on 29 Sep (skeleton; login and roles; fake-ERPNext sync; intake-to-procure with approval chain; 12 synthetic evaluation invoices). Step 2 (Bedrock spike) code done, live run waits on Bedrock model access. Update this line as milestones complete.

## Non-negotiables

- Synthetic data only. No secrets in the repo.
- No payments, GST filing, or ledger posting. ERP writes are draft Purchase Invoices only, and only through the outbox protocol (BUILD_PLAN §8).
- AI extracts and explains. Deterministic rules decide the match (§6). A named human approves, with segregation of duties enforced on the server (§9).
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
| Security review | `ecc:security-review` (`gstack-cso` is unavailable on Windows) |
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
