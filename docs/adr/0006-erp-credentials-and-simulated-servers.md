# ADR 0006: ERP keys are typed on the Connectors page and stored encrypted; simulated ERPs are in-process servers

**Date:** 12 Oct 2026 · **Status:** accepted (founder chose the Connect form) · **Plan:** BUILD_PLAN §4, §5 (`erp_connections`), §8, §9 · **Builds on:** ADR 0004

## Context
The founder will sign up for every free ERP plan at once, after Steps 12–20 are built, and wants the only remaining work to be
"create the account, connect it to Orrfin". Pasting keys into `.env` and restarting for each ERP is error-prone, and the keys are
company secrets: they must never appear in the repo, in logs, in audit events, in job rows or on screen.

## Decision
- **Connect form.** Each ERP card on `/connectors` (admin only) has the fields that ERP needs. Save → Test connection →
  Prepare demo data → Make active. Every action is audited; payloads name fields, never values.
- **Encryption at rest.** All of a connection's fields are one Fernet token in `erp_connections.credentials_encrypted`
  (`app/security/secrets.py`). The master key `ORRFIN_SECRET_KEY` lives only in `.env` (created by `scripts/dev.ps1`) or
  Secrets Manager on AWS. Keys are decrypted only in `app/adapters/registry.get_adapter`, for one call.
- **Write-only secrets.** The API returns "set" plus the last four characters. A blank secret on re-save keeps the stored one.
- **Outbound guard** (`app/security/outbound.py`): per-ERP host allow-list (https only for cloud ERPs; `localhost` only for
  Tally and Odoo; private IPs refused), no redirects, timeouts, and `redact()` on every error message. 4xx → `ErpRejected`
  (outbox FAILED); timeout, 429, 5xx, network → `ErpUnknown` (outbox UNKNOWN → look up first, §8).
- **One code path per ERP.** Each adapter is HTTP client code against the vendor's API. In *simulated* mode (and in every test)
  the same client talks to an in-process fake server through `httpx.MockTransport`, fed from the canonical dataset and keeping
  Orrfin's writes in `storage/erp-sim/` so lookups survive restarts. "Live-seeded" contract tests run the live seeder against a
  blank fake server, so "Prepare demo data" is tested without an account.
- **Activation rule.** Exactly one active connection per org (partial unique index). A live connection can be made active only
  after a passing Test connection; changing its keys drops it back to the same ERP's simulated mode.

## Consequences
- §5 gains `erp_connections.credentials_encrypted` (additive; founder approved). Losing `ORRFIN_SECRET_KEY` means re-entering keys.
- Live adapters are verified against fake servers built from the vendors' published API docs, not against the real systems.
  The first real connection may reveal a small shape difference; Test connection reports which call and field failed.
- Before any pilot (§12): move the master key to Secrets Manager, rotate it, and add per-tenant keys.
