"""ErpAdapter port: what Orrfin needs from any ERP, in Orrfin's own words (BUILD_PLAN §2, §4, §8; ADR 0004).

Only the `sync`, `connectors` and `erp_outbox` modules call an ErpAdapter, always through
`app.adapters.registry`. Adapters translate ERP documents into the records below; no ERP
field name appears outside app/adapters/. Only submitted (final) ERP documents are
returned by the list methods: drafts and cancelled documents are not mirrored.

Write-back (§8): adapters only ever create *drafts* that a human finalises inside the ERP.
Every write has a lookup twin (`find_bill`, `find_po`) that the outbox calls before any
retry after an UNKNOWN result, so a timeout can never create a second document.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

Label = Literal["live", "sandbox", "simulated"]


class ErpVendor(BaseModel):
    erp_ref: str
    name: str
    gstin: str | None
    state_code: str | None
    modified: datetime  # timezone-aware


class ErpPoLine(BaseModel):
    erp_ref: str
    line_no: int
    item_code: str
    description: str
    hsn: str | None
    uom: str | None
    qty: Decimal
    rate: Decimal
    amount: Decimal
    tax_rate: Decimal  # total GST %, e.g. 18


class ErpPurchaseOrder(BaseModel):
    erp_ref: str
    vendor_ref: str
    po_date: date | None
    schedule_date: date | None
    status: str  # open | to_bill | completed | closed | on_hold
    currency: str
    net_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    orrfin_ref: str | None  # set on POs Orrfin drafted (§8); None for POs created in the ERP
    modified: datetime
    lines: list[ErpPoLine]
    # The PO number printed on vendor invoices, when the ERP keeps it apart from its own record id
    # (Odoo "P00012" vs the canonical "PUR-ORD-2026-00001"). Invoices match on either.
    po_number: str | None = None


class ErpReceiptLine(BaseModel):
    erp_ref: str
    item_code: str
    qty_received: Decimal  # accepted quantity
    po_ref: str | None
    po_line_ref: str | None


class ErpReceipt(BaseModel):
    erp_ref: str
    vendor_ref: str
    posting_date: date | None
    status: str
    modified: datetime
    lines: list[ErpReceiptLine]


# --- Write-back (§8) ---------------------------------------------------------------------------

class Capabilities(BaseModel):
    """What this connection can do, shown on the Connectors page and checked before queuing a write."""
    label: Label
    can_read: bool = True
    can_write_bill: bool = True
    can_write_po: bool = True
    draft_bill_means: str = Field(description="What a 'draft bill' is in this ERP, in plain words")
    draft_po_means: str = Field(description="What a 'draft PO' is in this ERP, in plain words")
    # Why a write is refused, e.g. "SAP's sandbox is read-only". Empty when writes are allowed.
    write_note: str = ""


class DraftLine(BaseModel):
    item_code: str
    description: str
    hsn: str | None = None
    uom: str | None = None
    qty: Decimal
    rate: Decimal
    amount: Decimal
    tax_rate: Decimal = Decimal("0")
    po_line_ref: str | None = None  # the ERP's PO line id, for bills that bill a PO


class DraftBill(BaseModel):
    """A supplier invoice Orrfin approved, to be created as a *draft* bill in the ERP."""
    idempotency_key: str  # sha256(org|vendor_gstin|invoice_no_norm|fiscal_year), §8 step 1
    vendor_ref: str  # the ERP's own vendor id (from the mirror)
    vendor_gstin: str | None
    supplier_invoice_no: str
    invoice_date: date
    po_ref: str | None  # the ERP's own PO id
    currency: str = "INR"
    lines: list[DraftLine]
    net_total: Decimal
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    grand_total: Decimal


class DraftPo(BaseModel):
    """An approved purchase request, to be created as a *draft* PO in the ERP (§8 "Draft Purchase Orders")."""
    idempotency_key: str  # sha256(org|request_id|"purchase_order")
    request_number: str
    vendor_ref: str
    po_date: date
    schedule_date: date
    currency: str = "INR"
    lines: list[DraftLine]


class Created(BaseModel):
    erp_doc_name: str
    # For file-based ERPs (BUSY): the import file a human loads into the ERP.
    import_file: str | None = None


class CheckStep(BaseModel):
    name: str
    ok: bool
    detail: str


class ConnectionCheck(BaseModel):
    ok: bool
    steps: list[CheckStep]


class SeedReport(BaseModel):
    """What "Prepare demo data" did in the ERP: counts per record type, created vs already there."""
    created: dict[str, int]
    existing: dict[str, int]
    notes: list[str] = []


class ErpError(Exception):
    """Base for ERP failures. Messages are shown to finance, so they never carry a secret (redact())."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # the ERP's HTTP status, when there was one


class ErpRejected(ErpError):
    """The ERP clearly refused the request (validation, permissions). Retrying won't help: outbox FAILED."""


class ErpUnknown(ErpError):
    """Timeout, 5xx or network error: the write may or may not have happened. Outbox UNKNOWN → look up first."""


class ErpNotSupported(ErpError):
    """This connection cannot do that (e.g. a read-only sandbox). Checked before anything is queued."""


class ErpAdapter(Protocol):
    def capabilities(self) -> Capabilities: ...

    def test_connection(self) -> ConnectionCheck: ...

    def list_vendors(self) -> list[ErpVendor]: ...

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]: ...

    def list_receipts(self) -> list[ErpReceipt]: ...

    def create_draft_bill(self, bill: DraftBill) -> Created: ...

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None: ...

    def create_draft_po(self, po: DraftPo) -> Created: ...

    def find_po(self, orrfin_key: str) -> str | None: ...

    def seed_demo_data(self) -> SeedReport: ...
