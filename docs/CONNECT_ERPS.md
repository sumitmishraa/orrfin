# Connect your ERP accounts to Orrfin

**For:** the founder, on the day you create the free ERP accounts. **Built in:** PROMPTS Steps 12–20. **Why it's safe:** [ADR 0006](adr/0006-erp-credentials-and-simulated-servers.md).

Everything in Orrfin is already built. For each ERP you only do two things: **create the account**, then **connect it**.
Connecting is the same five clicks for every ERP:

```
Create the free account ─► copy its keys ─► Orrfin: Connectors page
      │
      ▼
 1. Paste the keys ─► 2. Save keys ─► 3. Test connection ─► 4. Prepare demo data ─► 5. Make active
                                          │ (red ✗? read the line;                    │
                                          │  it says exactly what to fix)              ▼
                                                                    POs page ─► Sync from ERP ─► the 8 demo POs appear
```

**Before you start**
1. Start Orrfin: in PowerShell, `.\scripts\dev.ps1` (it also creates the key that encrypts your ERP keys).
2. Sign in as **Anita Desai** (admin): `anita.admin@demo.orrfin.ai` / `Orrfin@Demo2026`.
3. In the left menu, click **Connectors**.

**Keeping company details safe**
- Paste keys **only** into the Connectors page, never into chat, email or a document.
- Orrfin stores them encrypted and never shows them again (you will see "saved …1234").
- Use the trial companies only with the synthetic demo data. Never load real company data (BUILD_PLAN §12).
- To remove keys from Orrfin: **Disconnect** on the card. To revoke them for good, delete the key inside the ERP too.

**What "Prepare demo data" does:** it creates the same 5 vendors, items, 8 purchase orders and 8 goods receipts in your ERP
(and switches on the ERP's own duplicate checks). Running it twice creates nothing new. Prefer a terminal?
`backend\.venv\Scripts\python backend\scripts\prepare_erp.py --system <erp> --mode live --activate`

**Check that it works** (any ERP): POs → **Sync from ERP** → 8 POs. Then Invoices → upload `evals/extraction/01-clean-match.pdf`
→ confirm → it matches → approve as Vikram. A **draft** bill appears in your ERP (see each section for where to look).

---

## ERPNext (Live, 14-day free trial)

**Create the account**
1. Go to **frappecloud.com** → **Sign up** → choose **ERPNext** → start the free trial.
2. In the setup wizard: country **India**, currency **INR**, company **Orrfin Demo Pvt Ltd**. Finish the wizard.

**Get the keys**
3. In ERPNext, click your avatar (top right) → **My Settings** → **Settings** tab → **API Access** → **Generate Keys**.
4. A box shows the **API Secret** once. Keep that tab open. The **API Key** is shown on the same page.

**Connect**
5. Orrfin → Connectors → **ERPNext** card → fill in:
   - **Site address**: the address in your browser, e.g. `https://orrfin-demo.frappe.cloud`
   - **API key** and **API secret** from steps 3–4
   - **Company name**: only if you created more than one company
6. **Save keys** → **Test connection**. Two ✗ lines ("Orrfin Ref field", "uniqueness") are normal now.
7. **Prepare demo data** (about a minute). It adds the Orrfin Ref / Orrfin PO No fields to Purchase Order, turns on
   "Check Supplier Invoice Number Uniqueness", adds Input Tax CGST / SGST / IGST accounts, and loads the demo data.
8. **Test connection** again (all ✓) → **Make active**.

**Where drafts appear:** ERPNext → **Buying → Purchase Invoice** (status *Draft*) and **Buying → Purchase Order** (status *Draft*).
A person submits them in ERPNext; Orrfin never does.

**If something fails**
- "refused the credentials (401/403)": regenerate the keys (step 3) and paste both again.
- "has no company yet": finish ERPNext's setup wizard first.
- "is not an allowed address": the site address must start with `https://`.
