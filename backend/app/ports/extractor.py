"""Extractor port: read an invoice PDF into fields with evidence (BUILD_PLAN §7 AI extraction contract).

Only the `invoices` module calls an Extractor (§4). Money and quantities come back as decimal
strings and are turned into Decimal by the caller, so they never pass through float. Model
confidence is carried for display only; it is never used as a gate (§7).
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class FieldEvidence(BaseModel):
    field: str = Field(description="Which field this supports, e.g. invoice_no or lines[1].qty")
    quote: str = Field(description="The text exactly as printed on the invoice")
    page: int = Field(description="1-based page number")


class ExtractedLine(BaseModel):
    description: str
    item_code: str | None = None
    hsn: str | None = None
    qty: str
    rate: str
    amount: str


class ExtractedInvoice(BaseModel):
    vendor_name: str
    vendor_gstin: str
    buyer_gstin: str | None = None
    invoice_no: str
    invoice_date: str = Field(description="YYYY-MM-DD")
    po_reference: str | None = Field(default=None, description="The buyer's PO number as printed")
    place_of_supply: str | None = Field(default=None, description="Two-digit GST state code")
    currency: str = "INR"
    lines: list[ExtractedLine]
    subtotal: str
    cgst: str
    sgst: str
    igst: str
    total: str
    evidence: list[FieldEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class ExtractionResult(BaseModel):
    invoice: ExtractedInvoice
    model_id: str
    prompt_version: str
    raw_output: dict[str, Any]


class ExtractorUnavailable(Exception):
    """The extractor could not read this document now (outage, refusal, unknown file).

    The extract job retries with backoff and, after the last attempt, switches the invoice
    to manual entry: the workflow never blocks on AI (§7 "Provider outage").
    """


class Extractor(Protocol):
    def extract(self, pdf: bytes) -> ExtractionResult: ...
