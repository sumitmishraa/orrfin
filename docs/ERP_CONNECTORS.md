# ERP connectors: research and catalogue

**Owner:** BUILD_PLAN v2.2 §2, §4 and §8. **Written:** Step 11, 5 Oct 2026. **Read before:** Steps 12–20.

This file answers three questions for every ERP Orrfin plans to connect:
1. **What does Orrfin need from it?** Read vendors, POs and goods receipts. Write a *draft* bill and a *draft* PO. Look a document up before any retry.
2. **How do we reach it?** API, authentication and a test system.
3. **How will the demo label it?** Live, Sandbox or Simulated.

Facts marked **(unverified)** came from memory or secondary sources. Check each one against the vendor's docs in the step that builds the connector, and update this file.

---

## 1. Demo labels (the honesty rule)

BUILD_PLAN §13 forbids "works with every ERP". Every connector shows one of these badges on the Connectors page:

| Label | Meaning | What we may say |
|---|---|---|
| **Live** | Orrfin talks to a real running copy of that ERP (trial, free plan or local install). | "Connected live to a <ERP> test company." |
| **Sandbox** | The vendor's official public test API. Usually read-only, with the vendor's sample data. | "Reading SAP's official sandbox." |
| **Simulated** | Fixtures shaped exactly like the vendor's published API responses, run through the same contract tests as the live connectors. No real system. | "Built to <ERP>'s published API; needs a customer test system to go live." |

---

## 2. The catalogue

| # | ERP / product | Who uses it | Interface | Auth | Test system | Demo label | Step |
|---|---|---|---|---|---|---|---|
| 1 | **ERPNext** (Frappe) | Indian SMB / mid-market | REST `/api/resource/<DocType>` | API key + secret (token) | Frappe Cloud 14-day trial | **Live** | 13–15 |
| 2 | **TallyPrime** | Most Indian SMBs (§12: "most target customers run Tally") | XML over HTTP to the Tally desktop app (default port 9000) | None by default (runs on the customer's PC) → needs a local agent in production | Free Educational mode on the founder's laptop | **Live** | 16 |
| 3 | **BUSY** | Indian SMB, traders | No public API; XML / Excel voucher import–export; integrations through channel partners | n/a | None public | **Simulated** (file-based) | 16 |
| 4 | **Microsoft Dynamics 365 Business Central** | Mid-market, global + India | REST/OData API v2.0 `/api/v2.0/companies({id})/…` | Microsoft Entra ID OAuth 2.0 (client credentials) | 30-day trial; **needs a work email, not Gmail** | **Live** | 17 |
| 5 | **Microsoft Dynamics 365 Finance & Operations** | Large enterprise | OData data entities `/data/<Entity>` | Entra ID OAuth 2.0 | Partner/customer tier-1 environment only | **Simulated** | 17 |
| 6 | **SAP S/4HANA Cloud** (public + private; on-prem uses the same OData APIs) | Large enterprise | OData V2/V4 APIs (communication scenarios, e.g. SAP_COM_0057 for supplier invoices) | Basic / OAuth via communication user; CSRF token for writes | **SAP Business Accelerator Hub sandbox** (api.sap.com): free API key, read-only sample data | **Sandbox (read)** + **Simulated (write)** | 18 |
| 7 | **SAP Business One** | Mid-market | Service Layer (OData) `/b1s/v1/…` | Session login (`POST /Login`, cookie) | Partner demo licence only | **Simulated** | 18 |
| 8 | **Oracle Fusion Cloud ERP** | Large enterprise | REST `/fscmRestApi/resources/11.13.18.05/<resource>` | Basic or OAuth (IDCS) | Customer pod only | **Simulated** | 19 |
| 9 | **Oracle NetSuite** | Mid-market, fast-growing companies | SuiteTalk REST `/services/rest/record/v1/<record>` | OAuth 2.0 or token-based auth (TBA) | Customer sandbox only | **Simulated** | 19 |
| 10 | **Zoho Books** (India edition) | Indian SMB | REST `https://www.zohoapis.in/books/v3/…` | Zoho OAuth 2.0 (India data centre `accounts.zoho.in`) | **Free plan** (turnover < ₹25 lakh, 1,000 bills/year) | **Live** | 20 |
| 11 | **Odoo** (Community 19) | SMB / mid-market | JSON-2 API `POST /json/2/<model>/<method>` (XML-RPC/JSON-RPC deprecated in 19) | Bearer API key | Free: runs in Docker on the laptop | **Live** | 20 |

**Not planned for this prototype** (record the reason so investors get a straight answer):

| ERP | Reason |
|---|---|
| Sage Intacct, Acumatica, Epicor, Infor CloudSuite, Workday Financials | Low share among Orrfin's Indian target customers; no free test system. Add on demand: each is one adapter on the same plug. |
| QuickBooks Online | Intuit stopped selling QuickBooks Online in India **(unverified: check before saying it)**. |
| Marg ERP, other Indian desktop tools | Same pattern as BUSY (file import); add when a design partner needs one. |
| SAP ECC (old on-prem) | Uses IDocs/BAPIs, not modern OData; covered conceptually by the S/4HANA adapter. Pilot-only. |

---

## 3. Per-ERP mapping (what each Orrfin record is called in each ERP)

| Orrfin record | ERPNext | TallyPrime | Business Central | D365 F&O | SAP S/4HANA | SAP Business One | Oracle Fusion | NetSuite | Zoho Books | Odoo |
|---|---|---|---|---|---|---|---|---|---|---|
| Vendor | Supplier | Ledger under group "Sundry Creditors" | `vendors` | `VendorsV2` | `A_Supplier` (API_BUSINESS_PARTNER) | `BusinessPartners` (CardType = supplier) | `suppliers` | `vendor` | `contacts` (contact_type = vendor) | `res.partner` (supplier_rank > 0) |
| Purchase order | Purchase Order | Voucher type "Purchase Order" | `purchaseOrders` | `PurchaseOrderHeadersV2` + `PurchaseOrderLinesV2` | `A_PurchaseOrder` (API_PURCHASEORDER_PROCESS_SRV, being replaced by an OData V4 PO API) | `PurchaseOrders` | `purchaseOrders` | `purchaseOrder` | `purchaseorders` | `purchase.order` |
| Goods receipt | Purchase Receipt | Voucher type "Receipt Note" | `purchaseReceipts` (posted, read-only) **(unverified)** | Product receipt entities **(unverified name)** | Material document, movement type 101 (API_MATERIAL_DOCUMENT_SRV) | `PurchaseDeliveryNotes` (Goods Receipt PO) | `receivingReceiptRequests` (create) / receipt transactions (read) **(unverified)** | `itemReceipt` | Purchase receives **(unverified on the Books API)** | `stock.picking` (incoming) |
| Bill (supplier invoice) | Purchase Invoice | Voucher type "Purchase" | `purchaseInvoices` | `VendorInvoiceHeaders` + lines | `A_SupplierInvoice` (API_SUPPLIERINVOICE_PROCESS_SRV) | `PurchaseInvoices` | `invoices` (Payables) | `vendorBill` | `bills` | `account.move` (move_type = in_invoice) |
| Supplier invoice no. | `bill_no` | "Supplier Invoice No." (`REFERENCE`) **(unverified tag)** | `vendorInvoiceNumber` | `InvoiceNumber` | `SupplierInvoiceIDByInvcgParty` | `NumAtCard` | `InvoiceNumber` | `tranId` | `bill_number` | `ref` |

---

## 4. Write-back: how "draft" and "look up before retry" work in each ERP (BUILD_PLAN §8)

The §8 rules hold for every ERP:
- Orrfin only creates **drafts**, and a human finalises them inside the ERP.
- Every push goes through the outbox.
- After an UNKNOWN result (timeout, 5xx, network error), Orrfin **looks the document up before any retry**.

What changes per ERP is what "draft" means and which field the lookup uses.

| ERP | Draft bill = | Draft PO = | Lookup key for a bill | Lookup key for a PO | ERP-side safety net |
|---|---|---|---|---|---|
| ERPNext | `docstatus 0` | `docstatus 0` | supplier + `bill_no` | custom field `orrfin_ref` | "Check Supplier Invoice Number Uniqueness"; `orrfin_ref` Unique |
| TallyPrime | **Optional voucher** (`ISOPTIONAL = Yes`: does not touch the books until a human regularises it) **(unverified tag)** | Optional "Purchase Order" voucher | party ledger + Supplier Invoice No. | `orrfin:<key>` in the voucher narration | Tally has no uniqueness setting → the lookup is the only net; say so |
| BUSY (simulated) | Generated XML import file; a human imports it | Same | file name = idempotency key | Same | Human import step |
| Business Central | Unposted purchase invoice (API-created invoices are not posted) | Purchase order with status Open (not released) | `vendorNumber` + `vendorInvoiceNumber` | `orrfin:<key>` in the PO's `vendorOrderNumber` **(unverified field choice)** | BC rejects posting a duplicate external document no. per vendor **(unverified)** |
| D365 F&O (simulated) | Pending vendor invoice (`VendorInvoiceHeaders`, not posted) | PO in approval status Draft (with change management on) | `InvoiceAccount` + `InvoiceNumber` | `orrfin:<key>` in a PO reference field **(unverified)** | AP parameter "check invoice number used" **(unverified)** |
| SAP S/4HANA (simulated write; sandbox is read-only) | **Parked** supplier invoice **(unverified: how parking is set through the API)** | No draft PO through the API → Orrfin writes a **purchase requisition** (API_PURCHASEREQ_PROCESS_SRV), and the buyer converts it to a PO in SAP **(design choice)** | `InvoicingParty` + `SupplierInvoiceIDByInvcgParty` + fiscal year | `orrfin:<key>` in the requisition header text | SAP duplicate-invoice check (message M8 108) **(unverified)** |
| SAP Business One (simulated) | `Drafts` with DocObjectCode = purchase invoice | `Drafts` with DocObjectCode = purchase order | `CardCode` + `NumAtCard` | `orrfin:<key>` in `Comments` | none by default |
| Oracle Fusion (simulated) | Payables invoice created through REST stays **unvalidated** until a human validates it | `draftPurchaseOrders` resource **(unverified)** | `Supplier` + `InvoiceNumber` (filter with `q=`) | `orrfin:<key>` in the PO description | Payables rejects a duplicate invoice number per supplier |
| NetSuite (simulated) | `vendorBill` with approval status "Pending Approval" (needs the approval workflow) | `purchaseOrder` "Pending Supervisor Approval" | **`externalId` = idempotency key**: `PUT /record/v1/vendorBill/eid:<key>` is an upsert, so retries can't duplicate | Same, `eid:<key>` | externalId is unique per record type, the strongest net in the list |
| Zoho Books | Bill in status `draft` **(unverified on bills; confirmed for POs)** | PO in status `draft` | vendor + `bill_number` | `orrfin:<key>` in `reference_number` | Zoho warns on a duplicate bill number **(unverified)** |
| Odoo | `account.move` in state `draft` | `purchase.order` in state `draft` (RFQ) | partner + `ref` | `orrfin:<key>` in `origin` / `partner_ref` | Odoo warns on a duplicate vendor reference |

**Design consequence for Step 12:** the `ErpAdapter` port gets `find_bill(supplier_invoice_no, vendor_ref)` and `find_po(orrfin_key)`. Each adapter maps those to its own lookup above. The outbox code never needs to know which ERP it talks to.

---

## 5. Connector notes (gotchas to plan for)

- **TallyPrime.**
  - Runs on the customer's Windows PC, not in the cloud. A production connector needs a small **local agent** that calls `http://localhost:9000` and talks to Orrfin over HTTPS (already a §12 gate).
  - In the demo, Orrfin calls the founder's laptop directly.
  - Educational mode only allows vouchers on some dates of each month (we believe the 1st, 2nd and 31st **(unverified)**), so the Tally fixtures must use those dates.
  - Tally replies in XML, with amounts as signed strings (negative = credit).
- **Business Central.**
  - The trial needs a **work email**: Gmail, Outlook.com and Hotmail are refused. Use name@orrfin.ai, or start a Microsoft 365 trial first.
  - Register an app in Microsoft Entra, give it the "Dynamics 365 Business Central" API permission, and add the app in BC ("Microsoft Entra Applications").
  - The trial lasts 30 days, so start it close to the pitch.
- **SAP sandbox.**
  - The API key goes in the `APIKey` header.
  - The data is SAP's sample data, not ours. Orrfin maps whatever POs exist there.
  - Writes are blocked by design.
  - API_PURCHASEORDER_PROCESS_SRV (V2) is deprecated in favour of an OData V4 PO API. Check on api.sap.com that the chosen API still has a sandbox.
- **Odoo 19.** Use JSON-2 (`/json/2/...` with a Bearer API key). XML-RPC/JSON-RPC are deprecated: removal is announced for Odoo 22 (self-hosted) and 21.1 (Odoo Online).
- **Zoho Books.**
  - India accounts use the `.in` domains (`accounts.zoho.in`, `www.zohoapis.in`).
  - Every call needs `organization_id`.
  - The free plan caps bills at 1,000 a year (plenty for a demo).
- **NetSuite.** The externalId upsert is a model idempotency mechanism. Mention it in the pitch as "for ERPs that support it, we use the ERP's own idempotency".
- **India GST.** Only ERPNext, Tally, Zoho Books and Business Central (India localisation) carry GSTIN and HSN natively in the demo. In simulated global ERPs, GSTIN lives in the vendor tax-registration field; each adapter maps it into `ErpVendor.gstin`.

---

## 6. Founder actions, in the order the steps need them

| Step | What you do by hand | Cost |
|---|---|---|
| 13 | Frappe Cloud ERPNext trial (14 days) + API keys | Free trial |
| 16 | Install TallyPrime from tallysolutions.com, open it in **Educational mode**, create company "Orrfin Demo Pvt Ltd", enable the HTTP server: F1 Help → Settings → Connectivity → "TallyPrime acts as" = Both, port 9000 **(menu path unverified)** | Free |
| 17 | Business Central trial with a work email; an Entra app registration | Free 30 days |
| 18 | Free account at api.sap.com → "Show API Key" | Free |
| 20 | Zoho Books India free plan → API console (api-console.zoho.in) → a self-client | Free |
| 20 | Nothing for Odoo: it runs in Docker | Free |

---

## Sources
- Tally XML integration: [help.tallysolutions.com/xml-integration](https://help.tallysolutions.com/xml-integration/), [XML message formats](https://help.tallysolutions.com/xml-message-formats), [Integration with TallyPrime](https://help.tallysolutions.com/?p=149532)
- BUSY integration FAQ: [busy.in/faqs/third-party-services/integration](https://busy.in/faqs/third-party-services/integration), [voucher import/export](https://busy.in/faqs/data-conversion/voucher-import-export/8/)
- Business Central API: [purchaseInvoices (v2.0)](https://learn.microsoft.com/fi-fi/dynamics365/business-central/dev-itpro/api-reference/v2.0/api/dynamics_purchaseinvoice_get), [purchaseOrders (v2.0)](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/api/dynamics_purchaseorder_get), [trial sign-up and work email](https://learn.microsoft.com/en-us/dynamics365/business-central/across-faq)
- D365 F&O: [Vendor invoice header entity](https://learn.microsoft.com/lt-lt/dynamics365/fin-ops-core/dev-itpro/data-entities/entity-vendor-invoice-header-vendorinvoiceheader), [import vendor invoices](https://learn.microsoft.com/en-us/dynamics365/guidance/resources/import-vendor-invoices)
- SAP: [SAP Business Accelerator Hub sandbox (SAP Learning)](https://learning.sap.com/learning-journeys/discover-sap-business-technology-platform/illustrating-the-sap-business-accelerator-hub_c913055d-dbfb-4b85-84c9-508eb7468236), [S/4HANA procurement APIs](https://learning.sap.com/courses/implementing-sap-s-4hana-cloud-public-edition-sourcing-and-procurement/working-with-apis-in-sourcing-and-procurement_fbe601e4-22d1-49a4-9784-d8b6c6825658), [parking a supplier invoice via API (SAP Community)](https://answers.sap.com/t5/enterprise-resource-planning-q-a/how-to-park-a-supplier-invoice-with-api-supplierinvoice-process-srv-with/qaq-p/12303133)
- SAP Business One Service Layer: [SAP B1 purchasing connector overview](https://wso2.com/integration-platform/docs/connectors/catalog/erp-business/sap.businessone.purchasing/overview), [SAP B1 API guide](https://www.apideck.com/blog/sap-business-one-api-integration-guide.md)
- Oracle Fusion: [Procurement REST resources (25B)](https://docs.oracle.com/en/cloud/saas/readiness/scm/25b/proc25b/25B-procurement-wn-f36643.htm), [Receiving receipt requests REST](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/24c/fasrp/api-inventory-management-receiving-receipt-requests.html), [Fusion Financials REST guide](https://www.cleverence.com/articles/oracle-documentation/rest-api-for-oracle-fusion-cloud-financials-6371/)
- NetSuite: [vendor bill externalId discussion](https://archive.netsuiteprofessionals.com/t/26808499/rest-services-record-v1-vendorbill-externalid-01057111-trand), [PO-to-bill matching](https://nanonets.com/blog/match-purchase-orders-to-multiple-vendor-bills-in-netsuite/)
- Zoho Books: [free plan in India](https://www.patronaccounting.com/blog/zoho-books-pricing-india-2026), [PO statuses](https://www.zoho.com/books/help/purchase-order/manage-po.html), [API gotchas](https://developers.apideck.com/apis/accounting/zoho-books/gotchas)
- Odoo: [External RPC API (deprecation)](https://www.odoo.com/documentation/saas-19.4/developer/reference/external_rpc_api.html), [Odoo 19 XML-RPC deprecated](https://xyphen-it.nl/en/knowledge-base/odoo-19-xml-rpc-deprecated)
