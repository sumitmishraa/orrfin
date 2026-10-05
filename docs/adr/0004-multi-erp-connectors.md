# ADR 0004: One ERP port, many connectors; every connector is labelled Live, Sandbox or Simulated

**Date:** 5 Oct 2026 · **Status:** accepted (founder) · **Plan:** BUILD_PLAN v2.2 §2, §4, §5, §8, §11, §13; `docs/ERP_CONNECTORS.md`

## Context
Investors need to see that Orrfin can work with the ERPs companies actually run: Tally and Zoho for small Indian firms, ERPNext, Odoo and
Business Central for mid-market, SAP, Oracle and Dynamics F&O for large companies. v2.1 connected only ERPNext. Most large-company ERPs
have no free test system a startup can use this month, and §13 forbids claiming "works with every ERP".

The code already isolates ERP knowledge: `app/ports/erp.py` (`ErpAdapter`) speaks Orrfin's language, and only `app/adapters/` knows ERPNext
field names. Write-back (§8) was not yet built.

## Decision
- Keep **one** `ErpAdapter` port. Extend it with `capabilities()`, `create_draft_bill`, `find_bill`, `create_draft_po` and `find_po` *before*
  the outbox is built (Step 12), so write-back is written once against the port (Steps 14–15).
- A registry picks the adapter from the org's active `erp_connections` row. Mirrored rows carry `erp_connection_id` (additive migration).
- 11 connectors (catalogue in ERP_CONNECTORS.md §2). Each carries a label shown in the UI:
  - **Live** (real trial, free plan or local install): ERPNext, TallyPrime, Business Central, Zoho Books, Odoo.
  - **Sandbox** (vendor's official read-only API): SAP S/4HANA reads.
  - **Simulated** (fixtures in the vendor's published API format): SAP writes, SAP Business One, Oracle Fusion, NetSuite, Dynamics F&O, BUSY.
- One canonical demo dataset is rendered into each ERP's native format. One shared contract suite and one failure-injection fixture run
  against every adapter.
- §8 safety rules are unchanged for every ERP. Each adapter defines what "draft" means and which key the lookup-before-retry uses
  (BUILD_PLAN §8 table). Where an ERP has no draft PO through its API (SAP S/4HANA), Orrfin drafts a purchase requisition instead.

## Consequences
- Adding an ERP later = one adapter + one renderer + passing the shared suite; the core (matching, review, audit, outbox) never changes.
- Five more build steps (16–20) before deploy. Simulated connectors are first in the cut order (keep one SAP, one Oracle, one Microsoft card).
- Simulated connectors prove the mapping, not the live connection. Before any pilot they must be rebuilt against the customer's test system
  and their "(unverified)" facts checked (BUILD_PLAN §12).
- Tally runs on a desktop PC: the public demo can show it only from the laptop, until the Tally local agent (stretch goal) exists.
- Two more trials to time (ERPNext 14 days at Step 13, Business Central 30 days at Step 17). Business Central needs a work email.
