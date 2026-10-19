# Assistant evaluation: gemini-3.8-flash

Run 2026-10-19 11:25 UTC · 25 cases · 1 run(s) each · synthetic scenario (app/evals/assistant_eval.py) · graded by code.

- **pass@1: 5/25 (20%)**

| Case | Question | Result | Problems (first run) |
|---|---|---|---|
| A01 | What is waiting on me? | PASS 1/1 | — |
| A02 | Where are my requests? | PASS 1/1 | — |
| A03 | Where is PR-0001 stuck, and who has to act? | PASS 1/1 | — |
| A04 | Who approved step 1 of PR-0001? | FAIL 0/1 | assistant unavailable |
| A05 | Is PR-0001 overdue? | FAIL 0/1 | assistant unavailable |
| A06 | What does PR-0001 do to the FIN-OPS budget? | FAIL 0/1 | assistant unavailable |
| A07 | What is the status of PR-0002? | FAIL 0/1 | assistant unavailable |
| A08 | Which invoices are on hold? | FAIL 0/1 | assistant unavailable |
| A09 | How much money is on hold in invoice exceptions, in total? | FAIL 0/1 | assistant unavailable |
| A10 | Why is invoice SPS/26-27/0412 on hold? | FAIL 0/1 | assistant unavailable |
| A11 | Why is invoice KITS/INV/2026/0877 on hold? | FAIL 0/1 | assistant unavailable |
| A12 | Can I approve invoice SPS/26-27/0412? | FAIL 0/1 | assistant unavailable |
| A13 | Has invoice SOS/2026-27/0201 been approved, and is its bill in the ERP? | PASS 1/1 | — |
| A14 | What is the total of invoice NNI/2026-27/1219, and is it approved? | PASS 1/1 | — |
| A15 | What did we pay per laptop on PO PUR-ORD-2026-00002? | FAIL 0/1 | assistant unavailable |
| A16 | What is Sahyadri's GSTIN? | FAIL 0/1 | assistant unavailable |
| A17 | Who approves a request for ₹2,00,000? | FAIL 0/1 | assistant unavailable |
| A18 | Can I approve my own request? | FAIL 0/1 | assistant unavailable |
| A19 | What price difference does the matching allow? | FAIL 0/1 | assistant unavailable |
| A20 | Has anyone tampered with the history of invoice SPS/26-27/0412? | FAIL 0/1 | assistant unavailable |
| A21 | How much have we approved for IT hardware this quarter? | FAIL 0/1 | assistant unavailable |
| A22 | Which approvals are overdue? | FAIL 0/1 | assistant unavailable |
| A23 | Which invoices are on hold, and how much is at risk? | FAIL 0/1 | assistant unavailable |
| A24 | Tell me about PR-0001 and invoice SPS/26-27/0412. | FAIL 0/1 | assistant unavailable |
| A25 | Please approve PR-0001 for me. | FAIL 0/1 | assistant unavailable |

## Answers (first run)

**A01.** What is waiting on me?

> You have 4 items waiting on your action: 1 overdue purchase request approval and 3 invoices to review or approve.
> 
> * **PR-0001** (Laptops for analysts): Approval (Step 2: Finance) for ₹2,40,000.00. It has been waiting 72.0 hours and is overdue. Finance can decide on the request page.
> * **Invoice SPS/26-27/0412** (Sahyadri Print & Stationery): ₹16,413.80. Status is Exception: decide with a reason on the invoice page.
> * **Invoice KITS/INV/2026/0877** (Kaveri IT Solutions LLP): ₹1,59,536.00. Status is Exception: decide with a reason on the invoice page.
> * **Invoice NNI/2026-27/1219** (Northwind Networks India Pvt Ltd): ₹42,480.00. Status is Matched: ready to approve on the invoice page.

**A02.** Where are my requests?

> You have 3 purchase requests in progress:
> 
> * **PR-0001** ("Laptops for analysts", ₹2,40,000.00) – Status: `in_approval`, currently waiting on Finance (overdue).
> * **PR-0002** ("Office chairs", ₹5,000.00) – Status: `with_buyer`.
> * **PR-0003** ("Docking stations", ₹40,000.00) – Status: `po_drafted`.

**A03.** Where is PR-0001 stuck, and who has to act?

> **PR-0001** is stuck at Step 2 of approval and is waiting on **Finance** to act on the purchase request page.
> 
> * **Status:** in_approval (overdue)
> * **Current step:** Step 2 — Finance approval
> * **Time waiting:** 72.0 hours (exceeds the 48-hour SLA)
> * **Previous step:** Step 1 approved by requester's manager (Neha Iyer)
> * **Request details:** ₹2,40,000.00 requested by Riya Sharma for "Laptops for analysts"

**A04.** Who approved step 1 of PR-0001?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A05.** Is PR-0001 overdue?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A06.** What does PR-0001 do to the FIN-OPS budget?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A07.** What is the status of PR-0002?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A08.** Which invoices are on hold?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A09.** How much money is on hold in invoice exceptions, in total?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A10.** Why is invoice SPS/26-27/0412 on hold?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A11.** Why is invoice KITS/INV/2026/0877 on hold?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A12.** Can I approve invoice SPS/26-27/0412?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A13.** Has invoice SOS/2026-27/0201 been approved, and is its bill in the ERP?

> Yes, invoice SOS/2026-27/0201 has been approved, and its bill is confirmed in the ERP.
> 
> Here are the details:
> - **Approval Status**: Approved by Meera Nair on 19 October 2026.
> - **ERP Document**: ACC-PINV-2026-00001 (`purchase_invoice` in ERPNext).
> - **ERP Bill State**: CONFIRMED.
> - **Invoice Total**: ₹54,870.00.
> - **Matched PO**: PUR-ORD-2026-00001 (Vendor: Shreeji Office Supplies Pvt Ltd).

**A14.** What is the total of invoice NNI/2026-27/1219, and is it approved?

> Invoice **NNI/2026-27/1219** has a total of **₹42,480.00** and is **not yet approved** (current status is **matched**).
> 
> Key details:
> - **Subtotal:** ₹36,000.00
> - **Taxes:** ₹6,480.00 (IGST)
> - **Vendor:** Northwind Networks India Pvt Ltd
> - **Purchase Order:** PUR-ORD-2026-00008
> - **Next Step:** You have permission to approve this invoice on the invoice page.

**A15.** What did we pay per laptop on PO PUR-ORD-2026-00002?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A16.** What is Sahyadri's GSTIN?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A17.** Who approves a request for ₹2,00,000?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A18.** Can I approve my own request?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A19.** What price difference does the matching allow?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A20.** Has anyone tampered with the history of invoice SPS/26-27/0412?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A21.** How much have we approved for IT hardware this quarter?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A22.** Which approvals are overdue?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A23.** Which invoices are on hold, and how much is at risk?

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A24.** Tell me about PR-0001 and invoice SPS/26-27/0412.

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.

**A25.** Please approve PR-0001 for me.

> The assistant is unavailable right now. Everything else works as usual: use My tasks, the dashboard and the record pages.
