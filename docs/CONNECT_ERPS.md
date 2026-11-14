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

---

## Oracle Fusion Cloud ERP and Oracle NetSuite (Simulated)

Neither has a free test system, so both run on fixtures shaped like their published REST APIs. **Use simulated** on
their cards to try them. NetSuite shows a stronger safety net: Orrfin upserts drafts by **external ID**, NetSuite's own
idempotency, so even a lost reply can't create a second bill.

---

## Zoho Books (Live, free plan)

**Create the account**
1. Go to **zoho.com/in/books** → **Sign up free** → country **India** → create organisation **Orrfin Demo Pvt Ltd**
   (GST registered). Note the **Organisation ID**: Settings → Organisation Profile.

**Give Orrfin access** (a "Self Client": no website or redirect needed)
2. Go to **api-console.zoho.in** → **Add Client** → **Self Client** → **Create**.
3. **Client Secret** tab → copy the **Client ID** and **Client Secret**.
4. **Generate Code** tab → Scope (copy exactly):
   `ZohoBooks.contacts.ALL,ZohoBooks.settings.ALL,ZohoBooks.purchaseorders.ALL,ZohoBooks.bills.ALL`
   → time duration **10 minutes** → description "Orrfin" → **Create** → copy the code. It works **once**, within minutes.

**Connect** (right after step 4)
5. Orrfin → Connectors → **Zoho Books** → paste **Client ID**, **Client secret**, **One-time code**, **Organisation ID**.
   Leave **Refresh token** blank (Orrfin fills it in) and **Draft bills checked?** as `no` → **Save keys**.
   Orrfin swaps the code for a long-lived refresh token, stored encrypted; the code is not kept.
6. **Test connection → Prepare demo data → Make active** → POs → **Sync from ERP**.

**Draft bills (one-time check):** Zoho's docs don't say for sure that a bill created through the API is a *Draft*.
Orrfin only ever creates drafts, so bills to live Zoho stay **off** until you check: set **Draft bills checked?** to
`yes`, save, approve one demo invoice in Orrfin, and look in Zoho Books → **Purchases → Bills**. If it shows **Draft**,
keep `yes`. If it shows **Open**, set it back to `no`, delete that bill in Zoho, and tell Claude. Draft **POs** work now
(Purchases → Purchase Orders → status Draft).

**Also:** receive the demo POs in Zoho (Purchase Order → **Receive**) to try the 3-way match; GST comes from Zoho's
own tax setup.

---

## Odoo (Live, on this computer in Docker)

Nothing to sign up for.
1. Make sure Docker Desktop is running, then in PowerShell: `.\scripts\odoo_setup.ps1`
   (first run downloads Odoo, about 1 GB). It creates the database and prints an **API key** once.
2. Orrfin → Connectors → **Odoo** → paste the **API key** (leave address and database blank) →
   **Save keys → Test connection → Prepare demo data → Make active** → POs → **Sync from ERP**.
3. Next time, start Odoo with Orrfin: `.\scripts\dev.ps1 -Odoo`. Stop it: `.\scripts\odoo_setup.ps1 -Stop`.
4. Something half-done or messy? `.\scripts\odoo_setup.ps1 -Reset` deletes the Odoo demo database and builds it
   again with a new API key: paste the new key into Orrfin and press **Prepare demo data** again.

**Where drafts appear:** Odoo (http://localhost:8069, login admin / admin) → **Accounting → Vendors → Bills** (Draft)
and **Purchase → Requests for Quotation**. Confirm an RFQ, then Sync: the request becomes "PO open".

## Step 36: eight more ERPs (simulated only)

QuickBooks Online, Xero, Sage Intacct, Sage 50/200, Acumatica, Focus X, Marg ERP and TallyPrime (UAE VAT)
appear on the Connectors page with the label **Simulated**. There are no keys to paste yet: each runs
against an in-process fake that uses the ERP's own resource and field names (`backend/app/adapters/dialects.py`).
Those names come from the vendors' public documentation and **have not been checked against a live tenant**.

To move one to a real account later: create the vendor's free developer/sandbox account, add a live mode
for that ERP (credentials fields, allowed host, OAuth where needed), and run the contract and failure suites
against it. Known gaps: QuickBooks Online and Xero have no goods-receipt document, so three-way matching
needs receipts recorded elsewhere; TallyPrime UAE uses 5% VAT, which the Indian demo data does not match.
