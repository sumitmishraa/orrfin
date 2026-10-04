"""Match job: build the engine's input from the database, run the §6 rules, store the result (PROMPTS Step 8).

The engine itself (app/modules/matching) is pure; this module is the bridge to the database.
"Invoiced to date" counts only other invoices that matched or were approved, so an invoice
stopped as an exception never uses up a PO line's received quantity.
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.claude_ai import ClaudeExplainer, build_client
from app.config import get_settings
from app.jobs import handler
from app.models import (
    Document,
    GoodsReceipt,
    GrnLine,
    Invoice,
    InvoiceLine,
    Job,
    MatchResult,
    PoLine,
    PurchaseOrder,
    Vendor,
)
from app.modules.audit.service import record_event, to_jsonable
from app.modules.invoices.service import invoice_lines
from app.modules.matching.config import RULE_SET_VERSION, Tolerances
from app.modules.matching.engine import is_stale, match
from app.modules.matching.explain import TEMPLATE_SOURCE, explain_from_rules
from app.modules.matching.types import InvoiceIn, InvoiceLineIn, MatchInput, PoIn, PoLineIn, PriorInvoice

COUNTS_TOWARD_INVOICED = ("matched", "approved")
DEFAULT_BUYER_STATE = "27"  # the demo company is in Maharashtra; used only if the invoice shows no buyer state
ZERO = Decimal("0")


def _buyer_state(invoice: Invoice) -> str:
    gstin = invoice.buyer_gstin or ""
    if gstin[:2].isdigit():
        return gstin[:2]
    return invoice.place_of_supply or DEFAULT_BUYER_STATE


def find_po(db: Session, invoice: Invoice) -> PurchaseOrder | None:
    if not invoice.po_reference:
        return None
    return db.scalar(select(PurchaseOrder).where(PurchaseOrder.org_id == invoice.org_id,
                                                 PurchaseOrder.erp_ref == invoice.po_reference.strip()))


def erp_snapshot(db: Session, po: PurchaseOrder | None) -> dict[str, Any]:
    """Last-modified stamps of the PO and its receipts, to detect staleness later (§6 rule 11)."""
    if po is None:
        return {"po": None, "receipts": {}}
    receipts = db.execute(
        select(GoodsReceipt.erp_ref, GoodsReceipt.erp_modified).distinct()
        .join(GrnLine, GrnLine.receipt_id == GoodsReceipt.id).join(PoLine, PoLine.id == GrnLine.po_line_id)
        .where(PoLine.po_id == po.id)).all()
    return {"po": po.erp_modified.isoformat(), "receipts": {ref: mod.isoformat() for ref, mod in sorted(receipts)}}


def po_line_quantities(db: Session, po: PurchaseOrder, exclude_invoice: uuid.UUID) -> list[dict[str, Any]]:
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).all()
    ids = [l.id for l in lines]
    received = dict(db.execute(select(GrnLine.po_line_id, func.sum(GrnLine.qty_received))
                               .where(GrnLine.po_line_id.in_(ids)).group_by(GrnLine.po_line_id)).all()) if ids else {}
    invoiced = dict(db.execute(
        select(InvoiceLine.po_line_id, func.sum(InvoiceLine.qty))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(InvoiceLine.po_line_id.in_(ids), Invoice.status.in_(COUNTS_TOWARD_INVOICED),
               Invoice.id != exclude_invoice)
        .group_by(InvoiceLine.po_line_id)).all()) if ids else {}
    return [{"line": l, "received": received.get(l.id, ZERO), "invoiced": invoiced.get(l.id, ZERO)} for l in lines]


def build_input(db: Session, invoice: Invoice) -> tuple[MatchInput, PurchaseOrder | None]:
    document = db.get(Document, invoice.document_id)
    po = find_po(db, invoice)
    vendor = db.get(Vendor, po.vendor_id) if po and po.vendor_id else None
    quantities = po_line_quantities(db, po, invoice.id) if po else []
    priors = db.execute(
        select(Invoice, Document.sha256).join(Document, Document.id == Invoice.document_id)
        .where(Invoice.org_id == invoice.org_id, Invoice.id != invoice.id, Invoice.confirmed_at.is_not(None))).all()
    inp = MatchInput(
        invoice=InvoiceIn(
            id=str(invoice.id), vendor_gstin=invoice.vendor_gstin or "", buyer_state_code=_buyer_state(invoice),
            invoice_no_norm=invoice.invoice_no_norm or "", fiscal_year=invoice.fiscal_year or "",
            document_sha256=document.sha256,
            lines=[InvoiceLineIn(l.line_no, l.description, l.item_code, l.hsn, l.qty, l.rate, l.amount)
                   for l in invoice_lines(db, invoice)],
            subtotal=invoice.subtotal or ZERO, cgst=invoice.cgst or ZERO, sgst=invoice.sgst or ZERO,
            igst=invoice.igst or ZERO, total=invoice.total or ZERO),
        po=PoIn(erp_ref=po.erp_ref, status=po.status, vendor_gstin=vendor.gstin if vendor else None) if po else None,
        po_lines=[PoLineIn(id=str(q["line"].id), erp_ref=q["line"].erp_ref, item_code=q["line"].item_code,
                           hsn=q["line"].hsn, qty=q["line"].qty, rate=q["line"].rate, tax_rate=q["line"].tax_rate,
                           received_to_date=q["received"], invoiced_to_date=q["invoiced"]) for q in quantities],
        prior_invoices=[PriorInvoice(id=str(p.id), vendor_gstin=p.vendor_gstin, invoice_no_norm=p.invoice_no_norm,
                                     fiscal_year=p.fiscal_year, total=p.total, document_sha256=sha)
                        for p, sha in priors],
        tolerances=Tolerances(),
    )
    return inp, po


def explain(rule_results: list[dict[str, Any]], outcome: str, amount_at_risk: Decimal) -> tuple[str, str]:
    """Claude explains from rule results only; any AI failure falls back to the template (never blocks)."""
    settings = get_settings()
    if settings.ai_provider != "fake":
        try:
            explainer = ClaudeExplainer(*build_client(settings))
            return explainer.explain(rule_results, outcome), explainer.source
        except Exception:  # AI unavailable: the reviewer still gets a plain-English reason
            return explain_from_rules(rule_results, outcome, amount_at_risk), f"{TEMPLATE_SOURCE}; AI unavailable"
    return explain_from_rules(rule_results, outcome, amount_at_risk), TEMPLATE_SOURCE


def start_match(db: Session, invoice: Invoice, actor_id: uuid.UUID | None) -> None:
    """Queue matching for a confirmed invoice (same transaction as the confirmation)."""
    from app.jobs import enqueue

    invoice.status = "matching"
    enqueue(db, org_id=invoice.org_id, kind="match", payload={"invoice_id": str(invoice.id)}, created_by=actor_id)


@handler("match")
def run_match(db: Session, job: Job) -> dict[str, Any]:
    invoice = db.get(Invoice, uuid.UUID(job.payload["invoice_id"]), with_for_update=True)
    if invoice is None or invoice.status != "matching":
        return {"skipped": invoice.status if invoice else "missing"}
    inp, po = build_input(db, invoice)
    result = match(inp)
    rule_json = result.as_json()
    explanation, source = explain(rule_json, result.outcome, result.amount_at_risk)
    db.add(MatchResult(
        org_id=invoice.org_id, invoice_id=invoice.id, rule_set_version=result.rule_set_version,
        outcome=result.outcome, amount_at_risk=result.amount_at_risk, risk_score=result.risk_score,
        inputs_snapshot=to_jsonable({"erp": erp_snapshot(db, po), "tolerances": inp.tolerances.as_json(),
                                     "po": inp.po.__dict__ if inp.po else None,
                                     "po_lines": [l.__dict__ for l in inp.po_lines],
                                     "invoice": {k: v for k, v in inp.invoice.__dict__.items() if k != "lines"}}),
        rule_results=rule_json, explanation=explanation, explanation_source=source))
    for line in invoice_lines(db, invoice):
        pairing = result.pairings.get(line.line_no)
        line.po_line_id = uuid.UUID(pairing[0]) if pairing else None
        line.pairing_method = pairing[1] if pairing else None
    invoice.po_id = po.id if po else None
    invoice.vendor_id = po.vendor_id if po else None
    invoice.status = result.outcome
    failed = [r["code"] for r in rule_json if r["status"] == "fail"]
    record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=None,
                 action="matched" if result.outcome == "matched" else "exception_raised",
                 payload={"status": invoice.status, "rule_set_version": RULE_SET_VERSION,
                          "amount_at_risk": result.amount_at_risk, "risk_score": result.risk_score,
                          "failed": failed})
    return {"outcome": result.outcome, "failed": failed, "amount_at_risk": str(result.amount_at_risk)}


def current_staleness(db: Session, invoice: Invoice) -> bool:
    """True if the PO or a receipt changed in the ERP since this invoice was matched (§6 rule 11)."""
    latest = db.scalar(select(MatchResult).where(MatchResult.invoice_id == invoice.id)
                       .order_by(MatchResult.created_at.desc()).limit(1))
    if latest is None:
        return False
    po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else find_po(db, invoice)
    return is_stale(latest.inputs_snapshot.get("erp", {}), erp_snapshot(db, po))


def match_view(db: Session, invoice: Invoice) -> dict[str, Any] | None:
    """What the review page shows: the latest result and a PO / receipt / invoice comparison per line."""
    latest = db.scalar(select(MatchResult).where(MatchResult.invoice_id == invoice.id)
                       .order_by(MatchResult.created_at.desc()).limit(1))
    if latest is None:
        return None
    po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else find_po(db, invoice)
    vendor = db.get(Vendor, po.vendor_id) if po and po.vendor_id else None
    by_po_line: dict[uuid.UUID, list[InvoiceLine]] = defaultdict(list)
    for line in invoice_lines(db, invoice):
        if line.po_line_id:
            by_po_line[line.po_line_id].append(line)
    comparison = []
    for q in po_line_quantities(db, po, invoice.id) if po else []:
        billed = by_po_line.get(q["line"].id, [])
        comparison.append({
            "po_line": q["line"].line_no, "item_code": q["line"].item_code, "description": q["line"].description,
            "po_qty": str(q["line"].qty), "po_rate": str(q["line"].rate), "received": str(q["received"]),
            "invoiced_before": str(q["invoiced"]),
            "invoice_qty": str(sum((l.qty for l in billed), ZERO)) if billed else None,
            "invoice_rate": str(billed[0].rate) if billed else None,
        })
    return {
        "outcome": "stale" if current_staleness(db, invoice) else latest.outcome,
        "matched_outcome": latest.outcome, "amount_at_risk": str(latest.amount_at_risk),
        "risk_score": latest.risk_score, "rule_set_version": latest.rule_set_version,
        "rule_results": latest.rule_results, "explanation": latest.explanation,
        "explanation_source": latest.explanation_source, "matched_at": latest.created_at.isoformat(),
        "po": {"id": str(po.id), "erp_ref": po.erp_ref, "status": po.status,
               "vendor_name": vendor.name if vendor else None, "vendor_gstin": vendor.gstin if vendor else None}
        if po else None,
        "unpaired_lines": [l.line_no for l in invoice_lines(db, invoice) if l.po_line_id is None],
        "comparison": comparison,
    }
