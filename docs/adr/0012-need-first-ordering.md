# ADR 0012: Need-first intake and POs built by procurement

Date: 17 Nov 2026 · Status: accepted (founder, Step 42)

## Context

The founder described how the companies Orrfin sells to actually buy:
1. An employee WhatsApps or emails the General Manager what they need: the item and quantity, with no vendor and usually no price.
2. The GM approves the need.
3. The procurement manager collects the month's approved needs. Procurement knows the vendors and prices, so they draft the PO.
4. Procurement emails the PO to the vendor ("please find attached our purchase order").

The same order of steps appears elsewhere:
- In ERPNext, a Material Request has no supplier, and "Get Items From" pulls several requests into one Purchase Order.
- Precoro's "PO from requisitions" groups requests by supplier and merges identical items.
- Indian purchase SOPs raise the indent "without supplier details" and give the PO its own approval by amount, because the final vendor and price can differ from the request.

Orrfin's flow since Step 4 was buyer-first: the requester chose a category and a suggested vendor and entered rates, and the buyer completed it. Approvals came after pricing, and each request became its own ERP draft PO.

## Decision

1. **A per-org setting, `orgs.intake_flow`.** It is either `buyer_first` (unchanged) or `need_first`.
   - Existing orgs keep `buyer_first`. The demo org uses `need_first`.
   - Both flows stay, because some customers really do price on the request (and an RFQ award arrives already priced).
   - Virtual cards, spend reports and about 15 test files depend on the buyer-first statuses.
2. **Need-first requests:**
   - The employee states what, how many, by when and why. The price is optional (0 means unknown) and there is no vendor.
   - Submitting starts a chain with one step for the requester's manager, plus the category's named reviewer if it has one. A published request-approval workflow still decides this chain.
   - A requester with no manager goes to an admin, so a need can never wait on a step nobody may decide.
   - On approval the request becomes `with_buyer` ("With procurement"). Request statuses are reused (`in_approval`, `with_buyer`, `po_drafted` = all lines on a PO, `po_open` = ordered), so the CHECK constraint is unchanged.
3. **WhatsApp and email intake is paste-in.**
   - The message is kept word for word (`source_channel`, `source_message`). AI reads the items when it is available; otherwise a simple "number + item" reading does.
   - A manager or procurement may enter a need for an employee (`entered_by_id`). The draft belongs to the employee, who checks and submits it. The person asking therefore stays the requester, and no segregation-of-duties rule changes.
   - Orrfin sends and receives no real WhatsApp or email.
4. **Orrfin POs (`order_pos`, PO-0001):**
   - Procurement ticks approved need lines, picks one ERP vendor, and picks each line's ERP item code from the mirrored item list, with the last paid rate filled in.
   - Lines with the same item code and rate are merged. `order_po_line_sources` records which request line each PO line orders.
   - A partial unique index allows only one live PO per request line. Cancelling or rejecting the PO frees its lines.
5. **PO approval:**
   - The chain is the org's amount tiers *without* the manager step, because each need already has its manager's approval. With the demo tiers: up to ₹50,000 there is no step; up to ₹5 lakh, Finance; above that, Finance then Admin.
   - The person who built or submitted the PO cannot approve it, and nobody decides two steps of the same PO.
6. **ERP:**
   - On approval, one outbox row is created in the same transaction. Its `doc_type` is `purchase_order`, its `order_po_id` is set, and its key is `sha256(org|order_po_id|purchase_order)`. One ERP draft PO therefore covers all the needs.
   - Lookup-before-retry, draft-only and a human submitting in the ERP are unchanged (§8).
   - The outbox check `one_source` becomes "exactly one of invoice, request or order PO".
7. **Sending to the vendor is simulated:**
   - It is allowed only once the ERP has confirmed its draft, so the email and PDF carry the ERP PO number and the supplier's invoice will quote it. This keeps 3-way matching working.
   - Sending stores the email in `vendor_messages`, prints it through the console sender, marks the PO `sent` and the needs "Ordered", and notifies the employees.

## Consequences

- The PO is a new record that Orrfin owns until its ERP draft is confirmed. After that the ERP's PO is the order of record, mirrored as before (`purchase_orders.order_po_id`). This adds rows to BUILD_PLAN §2, §5 and §8, which the founder approved.
- Budget warnings in need-first orgs see little committed spend until procurement prices the need. The rough price an employee may enter is only a hint.
- Not done:
  - real inbound WhatsApp or email (it needs a provider and consent, and is out of the demo's scope);
  - splitting one request line across two POs;
  - an admin switch for `intake_flow` on the Rules page (it is set in the database or the seed).
