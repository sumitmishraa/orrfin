# ADR 0010: Workflows are versioned definitions run by a deterministic interpreter; AI may draft them, an admin publishes

**Date:** 12 Nov 2026 · **Status:** accepted · **Plan:** BUILD_PLAN v3.0 changes 39, 47; §5; §9 · **Builds on:** ADR 0007, 0009

## Context
Approval routing was fixed in code: category → buyer → amount tiers (§9). Customers need their own steps
and conditions, and the founder wants them built by chatting. A workflow that an AI could switch on by
itself would let one bad or manipulated prompt change who approves money.

## Decision
- **A workflow is data.** A definition is a JSON document: one trigger, then nodes of a fixed set of
  kinds (`condition`, `approval`, `task`, `notify`, `wait`, `erp_draft`) joined by edges. Conditions use
  a small expression language over named fields (amount, currency, category, entity, supplier risk
  level, custom form fields) with comparison and and/or only. No code, no loops, no network calls.
- **Validated before it can be saved as publishable:** one start, every node reachable, every path ends,
  no cycles, every approval names a role or a person, every field exists on the subject type.
- **Immutable versions.** Publishing writes a new `workflow_versions` row with its SHA-256; published
  rows are never updated. An instance is pinned to the version it started on.
- **Deterministic interpreter on the jobs table.** Advancing an instance is a job; each step change and
  its audit event commit in one transaction. The same definition and the same inputs always give the
  same path, which is what makes "simulate on sample data" trustworthy.
- **The engine routes; it does not authorise.** Every decision still passes
  `procurement.decision_refusal` (and the invoice and payment equivalents). A workflow can add steps; it
  cannot remove a segregation-of-duties rule or an approval limit.
- **The v2.1 approval chain becomes the default template**, so existing behaviour and tests stay valid.
- **AI drafts, an admin publishes.** The workflow-builder agent turns a chat description into a draft
  definition. The draft goes through the same validator, is shown as a diagram, and can be simulated.
  The agent has no publish tool. Publishing is an admin action through the normal endpoint, audited
  with the version hash; a change that lowers an approval requirement needs a second admin.

## Consequences
- New node kinds are a code change with tests, by design.
- Rules-page tier edits keep working: they edit the default template's parameters and still apply only
  to chains started after the edit.
- The simulation result is stored with the publish audit event, so a reviewer can see what the admin saw.

## Status of the build (14 Nov 2026)
Built: the definition format, validator, deterministic route evaluation, immutable versions, simulate,
publish with the second-admin rule, and the request approval chain reading the published version.
For requests the chain is still copied into `request_approvals` when approval starts, which is what
pins a running request to the steps it started with; no separate instance table was needed for that.
Not built yet: instances and steps on the jobs table and the `task`, `wait` and `erp_draft` step kinds.
They arrive with the first record type that needs a non-approval step (supplier onboarding, Step 32).
