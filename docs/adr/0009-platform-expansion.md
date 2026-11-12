# ADR 0009: Orrfin grows from the Control Gate into a procurement platform, on the same application

**Date:** 12 Nov 2026 · **Status:** accepted · **Plan:** BUILD_PLAN v3.0 changes 36–50 · **Builds on:** ADR 0004, 0007, 0008

## Context
The founder asked (12 Nov) for the full product family a procurement-orchestration platform offers, more
ERPs, a chat agent that builds workflows, a premium interface, a clean codebase and a hard security pass.
Steps 1–27 already give a tested base: intake and approvals, three-way matching, 11 ERP connectors, the
exactly-once outbox, a hash-chained audit trail, simulated payments, bank reconciliation, close and
GSTR-2B matching. A second, smaller Orrfin codebase exists outside this repository
(`Documents\Microsoft-Hackathon`, built 6–7 Nov) with first versions of sourcing, supplier onboarding,
risk and contracts.

## Decision
- **One application, this repository.** New products are modules of the existing modular monolith. No
  microservices, no second workflow engine, no graph database. The hackathon codebase is read as a
  reference for ideas; nothing is merged from it without the same tests this repository requires.
- **Independent design.** Products are specified from public capability descriptions and practitioner
  needs. No competitor code, screens, wording or branding is used.
- **Product-to-module map:**

  | Product | Module |
  |---|---|
  | Intake-to-Procure, Intake management | `modules/procurement`, `modules/intake_forms` |
  | Procure-to-Pay | `modules/invoices`, `matching`, `review`, `erp_outbox`, `payments` |
  | Workflow engine | `modules/workflow_engine` (ADR 0010) |
  | Supplier Onboarding | `modules/suppliers` + the supplier portal |
  | Risk Orchestration | `modules/supplier_risk` |
  | Sourcing | `modules/sourcing` |
  | AI Contract Orchestration | `modules/contracts` |
  | Global Payments | `modules/payments` + `ports/payment_provider.py` (mock bank) |
  | Vendor Cards | `modules/cards` + `ports/card_issuer.py` (mock issuer) |
  | Spend insights | `modules/insights` |
  | Integration ecosystem | `adapters/` registry, `modules/notifications` (webhooks, API keys) |
  | AI Procurement Concierge, Superagents | `modules/assistant` (proposal tools, tool groups) |
  | MCP | `app/mcp_server/` (the assistant's tools under a per-user key) |
  | App Studio | `modules/app_studio` (form + workflow + list view; no customer code) |
  | Platform overview | the app shell and `/platform` |

- **Safety rules that do not change:** synthetic data; no real money (global payments and vendor cards
  are simulated); no GST or VAT filing; no journals or ERP payment entries; ERP writes are draft POs and
  draft bills only, through the §8 outbox; the ERP owns the vendor master; AI extracts, explains, drafts
  and proposes but never decides; a named person approves, with segregation of duties on the server.
- **Honest labels.** Every new connector starts as *Simulated*. "Production-ready" means tested, secured,
  documented and deployable; a pilot with real data still needs the BUILD_PLAN §12 gates.

## Consequences
- Roughly eleven build steps (30–40), one tested, committed slice each; AWS deploy moves after them.
- A licensed bank or card partner can replace the mock provider behind its port without a rewrite, but
  only after its own compliance review.
- Tax rules for the UAE and the supplier-risk rule set need practitioner sign-off before a pilot.
