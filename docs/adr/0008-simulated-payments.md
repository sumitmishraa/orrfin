# ADR 0008: Payments, bank reconciliation, close and GSTR-2B are simulated, rule-based and draft-free of the ledger

**Date:** 19 Oct 2026 · **Status:** accepted · **Plan:** BUILD_PLAN v2.4 changes 28, 31–34, §6b, §6c · **Builds on:** ADR 0004, ADR 0007

## Context
The founder asked (18 Oct) to build everything the Zip/DualEntry guide recommends, including payments,
payment-risk checks, bank matching and month-end close, and chose: simulated payments (bank file + mock
bank), payments recorded in Orrfin only (no ERP payment entry), and a close cockpit without journals.
This changes the old non-negotiable "no payments". Real bank connections need a bank partnership and
RBI/NPCI-compliant setup, so none is built.

## Decision
- **Simulated money only.** An approved payment run produces a generic NEFT/RTGS bulk CSV (each bank has
  its own layout) and "Send to bank (simulated)" runs a mock bank job that marks lines paid with synthetic
  UTRs (or failed, for a seeded invalid IFSC) and writes a bank statement CSV. The job is idempotent.
- **Orrfin owns payment profiles** (PAN, TDS section, bank account, IFSC); the ERP keeps the vendor master.
  Bank changes are maker-checker: the person who changed them cannot verify them; only the last four
  digits of an account reach the audit trail.
- **Rules decide, AI never does** (§6b, §6c): `payments/tds.py` (194C, 194J, 194Q, 206AA, nearest rupee,
  `TDS_RULE_SET_VERSION`) and `payments/risk.py` (blocks and holds, `PAYMENT_RULE_SET_VERSION`) are pure,
  versioned and stored with every line. TDS rates and thresholds are to be confirmed by a CA.
- **Segregation of duties for money:** finance prepares; another finance/admin approves; never the preparer,
  never anyone who approved one of the run's invoices, never above the approval limit; holds need a reason;
  the approved bank file's SHA-256 is stored and re-checked on every download.
- **No ledger:** no journals and no ERP payment entries. TDS deducted is reported, not filed.

## Consequences
- The demo shows the full procure-to-pay loop without any real money or bank credentials.
- Before a pilot (§12): a bank integration with its own compliance review, CA sign-off on TDS, and a decision
  on whether payments are written back to the customer's ERP.
