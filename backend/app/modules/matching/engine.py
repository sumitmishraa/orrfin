"""The matching rules, in BUILD_PLAN §6 order. Pure: plain data in, MatchOutcome out.

Every rule reports a result (pass, fail, warn or info) in plain English, so a reviewer and the
AI explanation can see exactly why an invoice passed or stopped. Fuzzy description matching is
never used to pass an invoice (§6 rule 1): a line that cannot be paired exactly is an exception.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.matching.config import OPEN_PO_STATUSES, RISK_WEIGHTS
from app.modules.matching.tax import TAX_REGIMES, money, tax_id_name, tax_id_result, tax_name, tax_type_result
from app.modules.matching.types import InvoiceLineIn, MatchInput, MatchOutcome, PoLineIn, RuleResult

CENT = Decimal("0.01")
ZERO = Decimal("0")


def _pair(line: InvoiceLineIn, po_lines: list[PoLineIn], pct: Decimal) -> tuple[PoLineIn | None, str]:
    """§6 rule 1, in order: explicit PO line reference, item code, HSN + rate within 2%."""
    if line.po_line_ref:
        found = [p for p in po_lines if p.erp_ref == line.po_line_ref]
        if len(found) == 1:
            return found[0], "po_line_ref"
    if line.item_code:
        found = [p for p in po_lines if p.item_code.strip().upper() == line.item_code.strip().upper()]
        if len(found) == 1:
            return found[0], "item_code"
        if len(found) > 1:
            return None, "ambiguous"
    if line.hsn:
        found = [p for p in po_lines if p.hsn == line.hsn and p.rate and abs(line.rate - p.rate) / p.rate <= pct]
        if len(found) == 1:
            return found[0], "hsn_rate"
        if len(found) > 1:
            return None, "ambiguous"
    return None, "none"


def match(inp: MatchInput) -> MatchOutcome:
    inv, tol, regime = inp.invoice, inp.tolerances, inp.tax_regime
    if regime not in TAX_REGIMES:
        # An unknown regime must never fall back to another country's tax rules.
        raise ValueError(f"Unknown tax regime {regime!r}; expected one of {TAX_REGIMES}.")
    results: list[RuleResult] = []
    pairings: dict[int, tuple[str, str]] = {}
    tax_id = tax_id_name(regime)

    def _rupees(value: Decimal) -> str:
        """The amount in the invoice's own currency (₹ for rupees; the name is kept from rule set 2026.09.1)."""
        return money(value, inv.currency)

    # Rule 7 / §6d — the supplier's tax number is well formed for this regime (GSTIN or TRN).
    results.append(tax_id_result(regime, inv.vendor_gstin, inv.total))

    # Rule 10 (and a missing PO) — without an open PO nothing can be matched against.
    if inp.po is None:
        results.append(RuleResult("po_state", "PO_NOT_FOUND", "fail",
                                  "No synced purchase order matches the PO number on the invoice.", inv.total))
    elif inp.po.status not in OPEN_PO_STATUSES:
        results.append(RuleResult("po_state", "PO_NOT_OPEN", "fail",
                                  f"PO {inp.po.erp_ref} is {inp.po.status.replace('_', ' ')} in the ERP; "
                                  "it no longer accepts invoices.", inv.total))
    else:
        results.append(RuleResult("po_state", "OK", "pass", f"PO {inp.po.erp_ref} is open."))

    # §6d — the invoice must be in the PO's currency. Orrfin never converts to make a match pass.
    if inp.po is not None and inv.currency != inp.po.currency:
        results.append(RuleResult("currency", "CURRENCY_MISMATCH", "fail",
                                  f"The invoice is in {inv.currency} but PO {inp.po.erp_ref} is in "
                                  f"{inp.po.currency}.", inv.total))

    # Rule 6 — the invoice must come from the PO's vendor.
    if inp.po is not None:
        if inp.po.vendor_gstin and inv.vendor_gstin == inp.po.vendor_gstin:
            results.append(RuleResult("vendor", "OK", "pass", f"The invoice {tax_id} is the PO vendor's {tax_id}."))
        else:
            results.append(RuleResult("vendor", "VENDOR_MISMATCH", "fail",
                                      f"The invoice {tax_id} {inv.vendor_gstin} is not the PO vendor's {tax_id} "
                                      f"{inp.po.vendor_gstin}.", inv.total))

    # Rule 1 — pair every invoice line with a PO line.
    paired: dict[int, PoLineIn] = {}
    if inp.po is not None:
        for line in inv.lines:
            po_line, method = _pair(line, inp.po_lines, tol.pairing_rate_pct)
            if po_line is None:
                reason = ("it fits more than one PO line, so it is not guessed" if method == "ambiguous"
                          else "no PO line has its item code or HSN at this rate")
                results.append(RuleResult("pairing", "LINE_UNPAIRED", "fail",
                                          f"Line {line.line_no} ({line.description}) cannot be paired: {reason}.",
                                          line.amount, line.line_no, "line"))
            else:
                paired[line.line_no] = po_line
                pairings[line.line_no] = (po_line.id, method)
        if inv.lines and len(paired) == len(inv.lines):
            results.append(RuleResult("pairing", "OK", "pass", "Every line pairs with a PO line."))

    # Rule 2 — cumulative quantity: invoiced to date + this invoice ≤ received to date.
    billed: dict[str, Decimal] = defaultdict(Decimal)
    first_rate: dict[str, Decimal] = {}
    for line in inv.lines:
        if line.line_no in paired:
            billed[paired[line.line_no].id] += line.qty
            first_rate.setdefault(paired[line.line_no].id, line.rate)
    by_id = {p.id: p for p in inp.po_lines}
    for po_line_id, qty in billed.items():
        p = by_id[po_line_id]
        excess = p.invoiced_to_date + qty - p.received_to_date
        if excess > 0:
            excess = min(excess, qty)
            results.append(RuleResult(
                "quantity", "QTY_EXCEEDS_RECEIPT", "fail",
                f"{p.item_code}: {qty.normalize():f} billed now + {p.invoiced_to_date.normalize():f} billed before "
                f"= more than the {p.received_to_date.normalize():f} received ({excess.normalize():f} too many).",
                (excess * first_rate[po_line_id]).quantize(CENT), scope="line"))
    if billed and not any(r.code == "QTY_EXCEEDS_RECEIPT" for r in results):
        results.append(RuleResult("quantity", "OK", "pass", "No line bills more than was received."))

    # Rule 3 — price within tolerance of the PO rate.
    price_failed = False
    for line in inv.lines:
        p = paired.get(line.line_no)
        if p is None or not p.rate:
            continue
        variance = (line.rate - p.rate) / p.rate
        if abs(variance) > tol.price_pct:
            price_failed = True
            results.append(RuleResult(
                "price", "PRICE_VARIANCE", "fail",
                f"Line {line.line_no}: billed at {_rupees(line.rate)}, PO rate {_rupees(p.rate)} "
                f"({variance * 100:+.1f}%, tolerance {tol.price_pct * 100:.0f}%).",
                (abs(line.rate - p.rate) * line.qty).quantize(CENT), line.line_no, "line"))
    if paired and not price_failed:
        results.append(RuleResult("price", "OK", "pass", "Every paired line is within the price tolerance."))

    # Rules 4-5 — arithmetic, with per-line tax rounded half-up and ₹1.00 round-off accepted.
    arithmetic_failed = False

    def check(label: str, expected: Decimal, actual: Decimal, line_no: int | None = None) -> None:
        nonlocal arithmetic_failed
        diff = abs(expected - actual)
        if diff > tol.arithmetic_abs:
            arithmetic_failed = True
            results.append(RuleResult("arithmetic", "ARITHMETIC_MISMATCH", "fail",
                                      f"{label}: expected {_rupees(expected)}, the invoice says {_rupees(actual)}.",
                                      diff.quantize(CENT), line_no))
        elif diff > 0:
            results.append(RuleResult("arithmetic", "ROUND_OFF", "info",
                                      f"{label}: round-off of {_rupees(diff)} accepted.", line_no=line_no))

    for line in inv.lines:
        check(f"Line {line.line_no} quantity × rate", line.qty * line.rate, line.amount, line.line_no)
    check("Sum of lines vs subtotal", sum((l.amount for l in inv.lines), ZERO), inv.subtotal)
    po_rates = {p.tax_rate for p in inp.po_lines}
    uniform_rate = po_rates.pop() if len(po_rates) == 1 else None
    taxable_rates = [(paired[l.line_no].tax_rate if l.line_no in paired else uniform_rate, l.amount) for l in inv.lines]
    # Every tax column counts toward the total, whichever regime: a tax amount in the wrong
    # column is reported by the tax-type rule below, not hidden from the arithmetic.
    tax_charged = inv.cgst + inv.sgst + inv.igst + inv.vat
    if inp.po is not None and all(rate is not None for rate, _ in taxable_rates):
        expected_tax = sum(((amount * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
                            for rate, amount in taxable_rates), ZERO)
        check(f"Tax at the PO's {tax_name(regime)} rates", expected_tax, tax_charged)
    check("Subtotal + tax vs total", inv.subtotal + tax_charged, inv.total)
    if not arithmetic_failed:
        results.append(RuleResult("arithmetic", "OK", "pass", "Lines, tax and total add up."))

    # Rule 8 / §6d — the right kind of tax for the regime (India: place of supply; UAE: VAT only).
    results.append(tax_type_result(regime, inv, inp.po.vendor_gstin if inp.po else None))

    # Rule 9 — duplicates: same file, or same key (+ same total → blocking).
    duplicate = False
    for prior in inp.prior_invoices:
        if prior.id == inv.id:
            continue
        same_key = (prior.vendor_gstin, prior.invoice_no_norm, prior.fiscal_year) == (
            inv.vendor_gstin, inv.invoice_no_norm, inv.fiscal_year)
        if prior.document_sha256 == inv.document_sha256 or (same_key and prior.total == inv.total):
            duplicate = True
            results.append(RuleResult("duplicate", "DUPLICATE_BLOCKING", "fail",
                                      "This invoice was already received: same vendor, number, financial year "
                                      "and total (or the very same file).", inv.total))
            break
        if same_key:
            duplicate = True
            results.append(RuleResult("duplicate", "DUPLICATE_SUSPECTED", "warn",
                                      "Another invoice has the same vendor, number and financial year "
                                      "but a different total. Check it is not a duplicate."))
    if not duplicate:
        results.append(RuleResult("duplicate", "OK", "pass", "No earlier invoice with the same number."))

    failed = [r for r in results if r.status == "fail"]
    invoice_level = max((r.amount_at_risk for r in failed if r.scope == "invoice"), default=ZERO)
    line_level = sum((r.amount_at_risk for r in failed if r.scope == "line"), ZERO)
    amount_at_risk = min(max(invoice_level, line_level), inv.total).quantize(CENT) if failed else ZERO
    scored = {r.code for r in results if r.status in ("fail", "warn")}
    risk_score = min(100, sum(RISK_WEIGHTS.get(code, 10) for code in scored))
    return MatchOutcome(outcome="exception" if failed else "matched", rule_results=results,
                        amount_at_risk=amount_at_risk, risk_score=risk_score, pairings=pairings)


def is_stale(snapshot: dict[str, Any], current: dict[str, Any]) -> bool:
    """§6 rule 11: the PO or any receipt changed in the ERP after matching (compared by last-modified)."""
    return snapshot.get("po") != current.get("po") or snapshot.get("receipts") != current.get("receipts")
