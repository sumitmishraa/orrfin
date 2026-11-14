# Security review: Orrfin v3.0 (Step 38, 15 Nov 2026)

What was tried against the v3.0 platform, what was found, what was fixed, and what is still open.
Every fix has a test in `backend/tests/security/` or next to the feature, so a regression fails the build.
This is a review of a prototype on synthetic data, not a certification: no system is "unhackable", and
the open items below must be closed before real customer data (BUILD_PLAN §12).

## How it was done

- Attacked as: an outsider (no session), a supplier (portal session), each employee role, another org,
  an API key / MCP client, and a malicious document or chat message (prompt injection).
- Guides used: the Cloudflare `security-audit` skill, the `testing-*` skills in `.claude/skills/`
  (broken access control, BOLA, mass assignment, business logic, auth weaknesses, CSRF, SSRF, SQL
  injection, XSS, security headers, indirect prompt injection, Docker hardening), Trail of Bits
  `sharp-edges` and `variant-analysis`, and `owasp-security`.
- Tools run: the full pytest suite, `npm audit --omit=dev`. `pip-audit`, Semgrep/CodeQL and a DAST scan
  (HawkScan needs a key) were not available on this machine.

## Built in this pass

| Control | Where | Test |
|---|---|---|
| Two-step sign-in (TOTP, RFC 6238), secret encrypted, codes single-use, a code needed to switch it off | `auth/totp.py`, `auth/router.py` | `tests/security/test_attack_pass_v3.py` |
| Postgres row-level security on every business table with `org_id`, set per transaction from the signed-in user (and the API-key owner for MCP) | migration `c5f9d1e7a3b0`, `db.py`, `auth/dependencies.py`, `mcp_server.py` | `test_the_database_hides_and_refuses_another_orgs_rows` |
| CSRF guard, login lockout, session rotation, security headers, unsafe-settings refusal (Step 31a) | `security/http.py`, `auth/` | `tests/security/test_auth_hardening.py` |
| Signed webhooks with an SSRF allow-list checked at save and before each send, no redirects | `integrations/webhooks.py` | `test_integrations.py` |
| Hashed, expiring, revocable API keys; MCP accepts only a bearer key, never a cookie | `integrations/api_keys.py`, `mcp_server.py` | `test_integrations.py`, `test_agents.py` |
| Separate supplier login realm (own table, cookie, session); hashed single-use invitations | `suppliers/portal.py` | `test_suppliers.py` |
| AI proposals: bound to one person, single use, 30-minute expiry, SHA-256 checked, submitted through the normal service | `agents/proposals.py` | `test_agents.py` |
| Contract terms proposed by AI must quote text that is really in the PDF | `contracts/reader.py` | `test_contracts.py` |

## Findings and fixes

| # | Finding | Severity | Fixed by |
|---|---|---|---|
| 1 | A lone admin could publish a workflow asking for fewer approvals (the comparison skipped the built-in tier limits) | High | `workflow_engine/service.py` compares at every tier limit; a second admin must publish (Step 31b) |
| 2 | Next.js 16.3.6 had published advisories incl. **critical** unauthenticated RCE (Image Optimization with SVG; `use cache`) and SSRF | Critical | Upgraded to Next.js 16.4.6; `npm audit fix` for transitive packages. 17 findings → 6 (2 low, 4 moderate, all in dev-time tools) |
| 3 | Cross-org email uniqueness check would hide another org's supplier contact under row-level security and turn a clean 409 into a 500 | Medium | `supplier_users` (and other pre-sign-in lookup tables) left out of RLS by design; documented in the migration |
| 4 | A supplier could learn it was on the sanctions list or shared a bank account from its own to-do list | Medium | The portal shows only document/tax/questionnaire gaps; reviewer-only findings stay hidden (`portal.SHOWN_TO_SUPPLIER`) |
| 5 | Changing bank details after approval (classic payment fraud) | High | The record goes back to review and a 30-day hold applies (`portal.set_bank`, §6e) |
| 6 | Spreadsheet formula injection in CSV exports | Medium | Leading `= + - @` are neutralised in spend and bank files (`spend.as_csv`, `payments.csv_safe`) |
| 7 | Mass assignment: extra JSON fields (`status`, `invited_by`, `is_default`) | Checked, not exploitable | Pydantic input models drop unknown fields; test added |
| 8 | SQL injection through new text inputs (assistant/MCP filters, forms) | Checked, not exploitable | All queries are parameterised SQLAlchemy; test added |
| 9 | Upload tricks (renamed executables, SVG/HTML, path traversal in file names) | Checked, not exploitable | Magic-byte checks, storage keys built from hashes, downloads served as attachments with `nosniff` |

## Still open (must be closed before real data)

1. **Two-step sign-in is optional.** It should be required for admin and finance before a pilot (a setting plus an enrolment page).
2. **Webhook DNS rebinding window.** The host is re-checked before each send, but DNS can change between the check and the connection. Fix: resolve once, connect to that IP with the original Host/SNI.
3. **Supplier portal and worker run without row-level security** (the app's own org checks apply). Extending RLS to them needs a per-job org scope.
4. **Bot protection** (Cloudflare Turnstile) on the employee and supplier sign-in pages is not switched on: it needs the founder's Cloudflare keys.
5. **No backend dependency audit** (`pip-audit` not installed) and no static analysis (Semgrep/CodeQL) or DAST scan yet.
6. **6 remaining npm findings** (low/moderate, in the shadcn CLI and the MCP SDK used at development time). Upgrade when non-breaking versions ship.
7. **Rate limits** exist for sign-in, the assistant and MCP; other write routes rely on the reverse proxy (Cloudflare/WAF at deploy, Step 28).
8. **Legal and tax sign-off**: UAE VAT rules, TDS, supplier-risk weights and the synthetic sanctions list are placeholders until reviewed (BUILD_PLAN §12).
