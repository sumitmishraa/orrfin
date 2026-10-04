"""Plain data in and out of the matching engine (BUILD_PLAN §6). Money and quantities are Decimal."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.modules.matching.config import RULE_SET_VERSION, Tolerances

Status = Literal["pass", "fail", "warn", "info"]


@dataclass
class InvoiceLineIn:
    line_no: int
    description: str
    item_code: str | None
    hsn: str | None
    qty: Decimal
    rate: Decimal
    amount: Decimal
    po_line_ref: str | None = None  # an explicit PO line reference, when the invoice prints one


@dataclass
class InvoiceIn:
    id: str
    vendor_gstin: str
    buyer_state_code: str
    invoice_no_norm: str
    fiscal_year: str
    document_sha256: str
    lines: list[InvoiceLineIn]
    subtotal: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal


@dataclass
class PoIn:
    erp_ref: str
    status: str
    vendor_gstin: str | None


@dataclass
class PoLineIn:
    id: str
    erp_ref: str
    item_code: str
    hsn: str | None
    qty: Decimal
    rate: Decimal
    tax_rate: Decimal  # GST %, e.g. 18
    received_to_date: Decimal
    invoiced_to_date: Decimal  # on earlier invoices that matched or were approved


@dataclass
class PriorInvoice:
    id: str
    vendor_gstin: str | None
    invoice_no_norm: str | None
    fiscal_year: str | None
    total: Decimal | None
    document_sha256: str


@dataclass
class MatchInput:
    invoice: InvoiceIn
    po: PoIn | None
    po_lines: list[PoLineIn]
    prior_invoices: list[PriorInvoice] = field(default_factory=list)
    tolerances: Tolerances = field(default_factory=Tolerances)


@dataclass
class RuleResult:
    rule: str  # which §6 rule, e.g. "price"
    code: str  # e.g. PRICE_VARIANCE; "OK" when it passed
    status: Status
    message: str
    amount_at_risk: Decimal = Decimal("0")
    line_no: int | None = None
    # "line" problems add up; "invoice" problems put (up to) the whole invoice at risk.
    scope: Literal["line", "invoice"] = "invoice"

    def as_json(self) -> dict[str, Any]:
        return {"rule": self.rule, "code": self.code, "status": self.status, "message": self.message,
                "amount_at_risk": str(self.amount_at_risk), "line_no": self.line_no, "scope": self.scope}


@dataclass
class MatchOutcome:
    outcome: Literal["matched", "exception"]
    rule_results: list[RuleResult]
    amount_at_risk: Decimal
    risk_score: int
    pairings: dict[int, tuple[str, str]]  # invoice line_no → (po_line id, pairing method)
    rule_set_version: str = RULE_SET_VERSION

    def as_json(self) -> list[dict[str, Any]]:
        return [r.as_json() for r in self.rule_results]
