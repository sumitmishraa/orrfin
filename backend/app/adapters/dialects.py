"""Eight more ERPs, described as field maps over one shared adapter (BUILD_PLAN change 48, PROMPTS Step 36).

QuickBooks Online, Xero, Sage Intacct, Sage 50/200, Acumatica, Focus X, Marg ERP and TallyPrime in UAE
VAT mode all start **Simulated**: none has a free test tenant wired up here, so each runs against an
in-process fake that speaks its resource and field names. The names come from each vendor's public API
documentation (`docs`), but **none has been checked against a live tenant** (`verified` says so); that
check happens when the founder connects a real account (docs/ERP_CONNECTORS.md). Anything an ERP
cannot represent is declared in `gaps` instead of being faked: QuickBooks Online and Xero have no
goods-receipt document, so three-way matching needs receipts recorded elsewhere (not built yet).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dialect:
    system: str
    name: str
    segment: str
    docs: str
    verified: str
    note: str
    base_url: str
    envelope: str  # where the list sits in a GET reply; "{c}" is the collection name, "" = a bare list
    collections: dict[str, str]  # logical → resource: vendors, pos, receipts (optional), bills, po_drafts
    f: dict[str, str]  # logical field → vendor field (dots for nested, e.g. VendorRef.value)
    draft_value: str  # the status a draft document carries
    open_value: str
    closed_value: str
    draft_bill_means: str
    draft_po_means: str
    gaps: frozenset[str] = field(default_factory=frozenset)
    tax_percent: str | None = None  # VAT-mode ERPs render this tax rate instead of the canonical GST


COMMON = {"vendor_id": "Id", "vendor_name": "DisplayName", "vendor_tax": "TaxIdentifier", "modified": "LastUpdated",
          "po_id": "Id", "po_number": "DocNumber", "po_vendor": "VendorRef.value", "po_date": "TxnDate",
          "po_due": "DueDate", "po_status": "Status", "po_lines": "Line", "po_memo": "Memo", "po_currency": "Currency",
          "line_id": "LineNum", "line_item": "ItemCode", "line_desc": "Description", "line_qty": "Qty",
          "line_rate": "UnitPrice", "line_amount": "Amount", "line_tax": "TaxPercent",
          "rc_id": "Id", "rc_vendor": "VendorRef.value", "rc_date": "TxnDate", "rc_lines": "Line",
          "rc_line_id": "LineNum", "rc_item": "ItemCode", "rc_qty": "Qty", "rc_po": "POId", "rc_po_line": "POLineNum",
          "bill_id": "Id", "bill_vendor": "VendorRef.value", "bill_number": "VendorInvoiceNo", "bill_date": "TxnDate",
          "bill_memo": "Memo", "bill_status": "Status", "bill_lines": "Line"}


def _f(**overrides: str) -> dict[str, str]:
    return {**COMMON, **overrides}


DIALECTS: tuple[Dialect, ...] = (
    Dialect("quickbooks_online", "QuickBooks Online", "Global SMB (US, UK, India)",
            "https://developer.intuit.com/app/developer/qbo/docs/api/accounting", "not verified against a live tenant",
            "No goods-receipt document in QuickBooks Online: three-way matching needs receipts recorded outside it.",
            "https://sandbox-quickbooks.api.intuit.com/v3/company/9130000000000000", "QueryResponse.{c}",
            {"vendors": "Vendor", "pos": "PurchaseOrder", "bills": "Bill", "po_drafts": "PurchaseOrder"},
            _f(po_status="POStatus", vendor_tax="PrimaryTaxIdentifier", modified="MetaData.LastUpdatedTime"),
            "Draft", "Open", "Closed", "a Bill marked as draft in its memo (QuickBooks has no draft bill state)",
            "a purchase order with POStatus Draft", gaps=frozenset({"receipts"})),
    Dialect("xero", "Xero", "Global SMB (UK, AU, NZ, UAE)", "https://developer.xero.com/documentation/api/accounting/overview",
            "not verified against a live tenant",
            "No goods-receipt document in Xero: three-way matching needs receipts recorded outside it.",
            "https://api.xero.com/api.xro/2.0", "{c}",
            {"vendors": "Contacts", "pos": "PurchaseOrders", "bills": "Invoices", "po_drafts": "PurchaseOrders"},
            _f(vendor_id="ContactID", vendor_name="Name", vendor_tax="TaxNumber", modified="UpdatedDateUTC",
               po_id="PurchaseOrderID", po_number="PurchaseOrderNumber", po_vendor="Contact.ContactID", po_date="Date",
               po_due="DeliveryDate", po_lines="LineItems", po_memo="Reference", line_id="LineItemID", line_qty="Quantity",
               line_rate="UnitAmount", line_amount="LineAmount", line_desc="Description", bill_id="InvoiceID",
               bill_vendor="Contact.ContactID", bill_number="InvoiceNumber", bill_date="Date", bill_memo="Reference",
               bill_lines="LineItems"),
            "DRAFT", "AUTHORISED", "BILLED", "an ACCPAY invoice with Status DRAFT", "a purchase order with Status DRAFT",
            gaps=frozenset({"receipts"})),
    Dialect("sage_intacct", "Sage Intacct", "US/UK mid-market", "https://developer.intacct.com/api/purchasing/",
            "not verified against a live tenant", "Purchasing transactions: Purchase Order and PO Receiver documents.",
            "https://api.intacct.com/ia/api/v1", "ia::result",
            {"vendors": "objects/accounts-payable/vendor", "pos": "objects/purchasing/purchase-order",
             "receipts": "objects/purchasing/po-receiver", "bills": "objects/accounts-payable/bill",
             "po_drafts": "objects/purchasing/purchase-order"},
            _f(vendor_id="key", vendor_name="name", vendor_tax="taxId", modified="audit.modifiedDateTime",
               po_id="key", po_number="documentNumber", po_vendor="vendor.key", po_date="transactionDate",
               po_due="dueDate", po_status="state", po_lines="lines", po_memo="memo", rc_id="key", rc_vendor="vendor.key",
               rc_date="transactionDate", rc_lines="lines", rc_po="createdFrom.key", rc_po_line="createdFrom.line",
               bill_id="key", bill_vendor="vendor.key", bill_number="billNumber", bill_date="createdDate",
               bill_memo="description", bill_status="state", bill_lines="lines"),
            "draft", "pending", "closed", "a bill in state draft", "a purchase order in state draft"),
    Dialect("sage_50", "Sage 50/200", "UK & India SMB (desktop)", "https://developer.sage.com/accounting/",
            "not verified against a live tenant",
            "Desktop product: the simulated API stands for the Sage Business Cloud Accounting / SData interface.",
            "https://api.accounting.sage.com/v3.1", "$items",
            {"vendors": "contacts", "pos": "purchase_orders", "receipts": "goods_received_notes",
             "bills": "purchase_invoices", "po_drafts": "purchase_orders"},
            _f(vendor_id="id", vendor_name="name", vendor_tax="tax_number", modified="updated_at", po_id="id",
               po_number="reference", po_vendor="contact.id", po_date="date", po_due="delivery_date", po_status="status",
               po_lines="lines", po_memo="notes", rc_id="id", rc_vendor="contact.id", rc_date="date", rc_lines="lines",
               rc_po="purchase_order.id", rc_po_line="purchase_order_line", bill_id="id", bill_vendor="contact.id",
               bill_number="vendor_reference", bill_date="date", bill_memo="notes", bill_status="status",
               bill_lines="lines"),
            "DRAFT", "OPEN", "CLOSED", "a purchase invoice with status DRAFT", "a purchase order with status DRAFT"),
    Dialect("acumatica", "Acumatica", "Mid-market cloud ERP", "https://help.acumatica.com/ (contract-based REST API)",
            "not verified against a live tenant", "Contract-based REST endpoint Default/23.200.001.",
            "https://orrfin-demo.acumatica.simulated/entity/Default/23.200.001", "",
            {"vendors": "Vendor", "pos": "PurchaseOrder", "receipts": "PurchaseReceipt", "bills": "Bill",
             "po_drafts": "PurchaseOrder"},
            _f(vendor_id="VendorID.value", vendor_name="VendorName.value", vendor_tax="TaxRegistrationID.value",
               modified="LastModifiedDateTime.value", po_id="OrderNbr.value", po_number="VendorRef.value",
               po_vendor="VendorID.value", po_date="Date.value", po_due="PromisedOn.value", po_status="Status.value",
               po_lines="Details", po_memo="Description.value", line_id="LineNbr.value", line_item="InventoryID.value",
               line_desc="LineDescription.value", line_qty="OrderQty.value", line_rate="UnitCost.value",
               line_amount="ExtendedCost.value", line_tax="TaxPercent.value", rc_id="ReceiptNbr.value",
               rc_vendor="VendorID.value", rc_date="Date.value", rc_lines="Details", rc_line_id="LineNbr.value",
               rc_item="InventoryID.value", rc_qty="ReceiptQty.value", rc_po="POOrderNbr.value",
               rc_po_line="POLineNbr.value", bill_id="ReferenceNbr.value", bill_vendor="Vendor.value",
               bill_number="VendorRef.value", bill_date="Date.value", bill_memo="Description.value",
               bill_status="Status.value", bill_lines="Details"),
            "On Hold", "Open", "Closed", "a bill On Hold (not released)", "a purchase order On Hold"),
    Dialect("focus_x", "Focus X (Focus Softnet)", "India & GCC mid-market", "https://www.focussoftnet.com/ (REST API, partner docs)",
            "not verified: API documentation is shared with partners only",
            "Vouchers: Purchase Order and Material Receipt Note; drafts are unauthorised vouchers.",
            "https://orrfin-demo.focusx.simulated/Focus8API", "data",
            {"vendors": "Masters/Vendor", "pos": "Transactions/PurchaseOrder", "receipts": "Transactions/MaterialReceiptNote",
             "bills": "Transactions/PurchaseVoucher", "po_drafts": "Transactions/PurchaseOrder"},
            _f(vendor_id="sCode", vendor_name="sName", vendor_tax="GSTIN", modified="ModifiedDate", po_id="DocNo",
               po_number="sNarration", po_vendor="VendorAC", po_date="Date", po_due="DueDate", po_status="Authorization",
               po_lines="Body", po_memo="Remarks", rc_id="DocNo", rc_vendor="VendorAC", rc_date="Date", rc_lines="Body",
               rc_po="LinkPO", rc_po_line="LinkPOLine", bill_id="DocNo", bill_vendor="VendorAC",
               bill_number="SupplierInvNo", bill_date="Date", bill_memo="Remarks", bill_status="Authorization",
               bill_lines="Body"),
            "Pending", "Authorized", "Closed", "an unauthorised purchase voucher", "an unauthorised purchase order"),
    Dialect("marg", "Marg ERP 9+", "Indian SMB, pharma and distribution", "https://margcompusoft.com/ (Marg API, partner access)",
            "not verified: API access is through Marg partners",
            "Purchase Order and Purchase Challan (receipt); bills arrive as unposted purchase entries.",
            "https://orrfin-demo.marg.simulated/api", "Data",
            {"vendors": "Party", "pos": "PurchaseOrder", "receipts": "PurchaseChallan", "bills": "PurchaseBill",
             "po_drafts": "PurchaseOrder"},
            _f(vendor_id="PartyCode", vendor_name="PartyName", vendor_tax="GSTNo", modified="ModTime", po_id="VchNo",
               po_number="RefNo", po_vendor="PartyCode", po_date="VchDate", po_due="DueDate", po_status="Status",
               po_lines="Items", po_memo="Remark", rc_id="VchNo", rc_vendor="PartyCode", rc_date="VchDate",
               rc_lines="Items", rc_po="OrderNo", rc_po_line="OrderLine", bill_id="VchNo", bill_vendor="PartyCode",
               bill_number="BillNo", bill_date="VchDate", bill_memo="Remark", bill_status="Status", bill_lines="Items"),
            "Unposted", "Pending", "Completed", "an unposted purchase bill", "an unposted purchase order"),
    Dialect("tally_uae", "TallyPrime (UAE VAT)", "UAE SMB", "https://help.tallysolutions.com/ (XML/JSON over HTTP)",
            "not verified against a live company",
            "The same TallyPrime, with UAE VAT ledgers (5%) and TRNs on parties. Shown here at VAT 5%.",
            "http://localhost:9000/uae", "ENVELOPE.{c}",
            {"vendors": "LEDGER", "pos": "PURCHASEORDER", "receipts": "RECEIPTNOTE", "bills": "PURCHASE",
             "po_drafts": "PURCHASEORDER"},
            _f(vendor_id="NAME", vendor_name="MAILINGNAME", vendor_tax="VATTRN", modified="ALTEREDON", po_id="VOUCHERNUMBER",
               po_number="REFERENCE", po_vendor="PARTYLEDGERNAME", po_date="DATE", po_due="DUEDATE", po_status="STATUS",
               po_lines="INVENTORYENTRIES", po_memo="NARRATION", rc_id="VOUCHERNUMBER", rc_vendor="PARTYLEDGERNAME",
               rc_date="DATE", rc_lines="INVENTORYENTRIES", rc_po="ORDERNO", rc_po_line="ORDERLINE", bill_id="VOUCHERNUMBER",
               bill_vendor="PARTYLEDGERNAME", bill_number="SUPPLIERINVOICENO", bill_date="DATE", bill_memo="NARRATION",
               bill_status="STATUS", bill_lines="INVENTORYENTRIES"),
            "Optional", "Active", "Closed", "an optional (memorandum) purchase voucher",
            "an optional purchase order voucher", gaps=frozenset({"tax"}), tax_percent="5"),
)

BY_SYSTEM = {d.system: d for d in DIALECTS}
