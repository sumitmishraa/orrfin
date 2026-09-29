"""ErpAdapter port: what Orrfin needs from any ERP, in Orrfin's own words (BUILD_PLAN §2, §4).

Only the `sync` module calls an ErpAdapter. Adapters translate ERP documents into the
records below; no ERPNext field name appears outside app/adapters/. Only submitted
(final) ERP documents are returned: drafts and cancelled documents are not mirrored.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


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


class ErpAdapter(Protocol):
    def list_vendors(self) -> list[ErpVendor]: ...

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]: ...

    def list_receipts(self) -> list[ErpReceipt]: ...
