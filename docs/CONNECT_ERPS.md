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

---

## TallyPrime (Live, free Educational mode, on this computer)

**Create the company**
1. Go to **tallysolutions.com** → **Download TallyPrime** → install it on the same computer as Orrfin.
2. Open TallyPrime → **Work in Educational Mode** (free).
3. **Create Company**: name **Orrfin Demo Pvt Ltd**, country India, GST on. Keep the company open.
4. Press **F11 (Features)** → **Inventory** → set **Enable Purchase Order Processing** and
   **Use Tracking Numbers (Delivery/Receipt Notes)** to **Yes** → save. (Orrfin's demo POs and receipt notes need them.)

**Let Orrfin talk to Tally**
5. Press **F1 (Help) → Settings → Connectivity** (or **Exchange → Data Synchronisation → Client/Server Configuration**)
   → **TallyPrime acts as** = **Both**, **Port** = **9000** → save. Leave TallyPrime open while you use Orrfin.

**Connect**
6. Orrfin → Connectors → **TallyPrime** card → fill in:
   - **Tally address**: leave blank (it means `http://localhost:9000`)
   - **Company name in TallyPrime**: `Orrfin Demo Pvt Ltd` (exactly as in Tally)
   - **Educational mode?**: `yes`
7. **Save keys** → **Test connection** (✓ "Reach TallyPrime", ✓ "Company loaded").
8. **Prepare demo data**: creates units, stock items, the Purchase and Input CGST/SGST/IGST ledgers, the 5 vendors,
   8 Purchase Orders and 8 Receipt Notes. In Educational mode they are dated the 1st (orders) and 2nd (receipts).
9. **Make active** → POs → **Sync from ERP**.

**Where drafts appear:** Tally → **Display More Reports → Exception Reports → Optional Vouchers**. Orrfin's draft bills
are Optional *Purchase* vouchers (no effect on the books) and draft POs are Optional *Purchase Order* vouchers.
Regularise one in Tally to make it real.

**If something fails**
- "Could not reach TallyPrime": Tally is closed, or step 5 isn't saved, or another program uses port 9000.
- "Company … is not open": open the company in Tally (Alt+F3 / Select Company).
- "Tally refused it: …": the line quotes Tally's own message (for example a missing ledger). Run Prepare demo data again.

## BUSY (Simulated, file-based)

Nothing to sign up. BUSY has no API, so Orrfin's "draft" is an **XML import file**: on an approved invoice or request,
the ERP draft panel shows **Download the import file**; load it with BUSY's voucher import. Make it active from its card
(**Use simulated**) to try it.

---

## Microsoft Dynamics 365 Business Central (Live, 30-day trial)

**Create the account** (needs a **work email** such as you@orrfin.ai; Gmail and Outlook.com are refused)
1. Go to **dynamics.microsoft.com → Business Central → Try for free** → sign up with the work email → country **India**.

**Give Orrfin its own app login** (client credentials; the secret never leaves the Connectors page)
2. Go to **entra.microsoft.com → App registrations → New registration** → name **Orrfin** → **Register**.
   Copy the **Application (client) ID** and the **Directory (tenant) ID** from the Overview page.
3. **Certificates & secrets → New client secret** → copy the **Value** (shown once).
4. **API permissions → Add a permission → Dynamics 365 Business Central → Application permissions →
   API.ReadWrite.All → Add** → then **Grant admin consent**.
5. In Business Central, search **Microsoft Entra Applications** → **New** → paste the client ID → State **Enabled** →
   add the permission set **D365 BUS FULL ACCESS** → **Grant Consent** if asked.

**Connect**
6. Orrfin → Connectors → **Business Central** card → paste **Directory (tenant) ID**, **Application (client) ID**,
   **Client secret value**; **Environment** blank (= Production) unless you named it; **Company name** only if there
   are several.
7. **Save keys → Test connection → Prepare demo data → Make active** → POs → **Sync from ERP**.

**Two things Business Central's standard API can't do** (Prepare demo data tells you too):
- **Receipts**: open each demo PO in Business Central → **Post → Receive**, then Sync, to try the 3-way match.
- **GST**: tax amounts come from Business Central's own GST setup for the demo items.

**Where drafts appear:** **Purchasing → Purchase Invoices** (unposted) and **Purchase Orders** (status Open, not released;
vendor order no. starts with ORF-). Release a draft PO and Sync: the request becomes "PO open".

## Microsoft Dynamics 365 Finance & Operations (Simulated)

No free system exists. It runs on fixtures shaped like F&O's OData data entities; **Use simulated** on its card to try it.

---

## SAP S/4HANA Cloud (Sandbox reads, simulated write-back)

**Create the account**
1. Go to **api.sap.com** → **Log On** → create a free SAP account.
2. Click your name (top right) → **Settings** → **Show API Key** → copy it.

**Connect**
3. Orrfin → Connectors → **SAP S/4HANA Cloud** → paste the **API key** → **Save keys → Test connection → Make active**
   → POs → **Sync from ERP**.

**What you will see:** SAP's own **sample** suppliers, purchase orders and goods receipts (not Orrfin's demo data), so
the demo invoices won't match them. SAP's sandbox is read-only, so draft supplier invoices (parked) and purchase
requisitions (SAP's APIs have no draft PO) go to Orrfin's **simulated** SAP, and the page says "write simulated".
For the full demo flow with matching invoices, use **Use simulated** on the same card.

## SAP Business One (Simulated)

Needs a partner demo licence, so it runs on fixtures in the Service Layer's format. **Use simulated** on its card.
Drafts are B1 *Drafts* (A/P invoice and purchase order) that a person adds in B1.
