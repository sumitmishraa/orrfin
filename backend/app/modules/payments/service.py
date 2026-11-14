"""Simulated payments (BUILD_PLAN v2.4 change 31, §6b, §6c, §9; ADR 0008; PROMPTS Step 25).

No real money moves: an approved run produces a generic NEFT/RTGS bulk file, and "Send to bank
(simulated)" hands it to a mock bank job that marks each line paid with a synthetic UTR (or failed),
and writes the bank statement that Step 26 reconciles.

Controls, all on the server:
- payment profiles: a bank-detail change is "pending verification" until a second finance/admin
  person verifies it (the changer cannot); only the last 4 digits of accounts reach the audit trail;
- runs: finance prepares; another finance/admin person approves (never the preparer, never anyone
  who approved one of its invoices, never above their approval limit); blocking risk results stop
  submission; holds need the approver's written reason;
- the mock bank settles a run once: a second job for the same run changes nothing.
Every state change writes its audit event in the same transaction.
"""

import csv
import hashlib
import io
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.jobs import enqueue, handler
from app.models import (
    ErpOutbox,
    Invoice,
    Job,
    PaymentLine,
    PaymentRun,
    ReviewDecision,
    User,
    Vendor,
    VendorPaymentProfile,
)
from app.modules.audit.service import record_event
from app.modules.invoices.providers import get_file_store
from app.modules.invoices.validation import fiscal_year
from app.modules.payments.risk import PAYMENT_RULE_SET_VERSION, PaymentFacts, check_payment, has_block, holds
from app.modules.payments.tds import SECTIONS, TDS_RULE_SET_VERSION, TdsInput, compute_tds
from app.modules.workflows.budgets import rupees

ZERO = Decimal("0")
PAYMENT_ROLES = ("finance", "admin")
LIVE_LINE = ("pending", "paid")  # lines that count as paid or about to be paid
LIVE_RUN = ("draft", "submitted", "approved", "sent", "settled", "partly_failed")
RTGS_FROM = Decimal("200000")  # RTGS for ₹2 lakh and above, NEFT below
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_ACCOUNT = re.compile(r"^\d{9,18}$")
# The mock bank rejects this IFSC so the demo shows a failed payment (synthetic, never a real branch).
MOCK_BANK_INVALID_IFSC = "ORFN0000000"


def csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection: a cell starting with = + - @ (or a tab/CR) is read as text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def run_label(run: PaymentRun) -> str:
    return f"PAY-{run.number:04d}"


def _require_role(user: User) -> None:
    if user.role not in PAYMENT_ROLES:
        raise Forbidden("Only finance or an admin can work with payments.")


def _last4(account: str | None) -> str | None:
    return f"…{account[-4:]}" if account else None


# --- Vendor payment profiles ---------------------------------------------------------------------------------

def profile_for(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID) -> VendorPaymentProfile | None:
    return db.scalar(select(VendorPaymentProfile).where(VendorPaymentProfile.org_id == org_id,
                                                        VendorPaymentProfile.vendor_id == vendor_id))


def save_profile(db: Session, user: User, vendor_id: uuid.UUID, *, pan: str | None, tds_section: str | None,
                 payee_type: str, j_kind: str, account_name: str, bank_account: str, ifsc: str) -> VendorPaymentProfile:
    _require_role(user)
    vendor = db.scalar(select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == user.org_id))
    if vendor is None:
        raise NotFound("Vendor not found.")
    pan = (pan or "").strip().upper() or None
    ifsc, bank_account = ifsc.strip().upper(), re.sub(r"\s", "", bank_account)
    if tds_section not in (None, *SECTIONS):
        raise Invalid("TDS section must be 194C, 194J, 194Q or none.")
    if payee_type not in ("individual", "company", "other") or j_kind not in ("professional", "technical"):
        raise Invalid("Choose a valid payee type.")
    if not _ACCOUNT.match(bank_account):
        raise Invalid("Bank account number must be 9 to 18 digits.")
    if not _IFSC.match(ifsc):
        raise Invalid("IFSC must look like HDFC0001234.")
    profile = db.scalar(select(VendorPaymentProfile).where(VendorPaymentProfile.org_id == user.org_id,
                                                           VendorPaymentProfile.vendor_id == vendor_id).with_for_update())
    created = profile is None
    if created:
        profile = VendorPaymentProfile(org_id=user.org_id, vendor_id=vendor_id, account_name=account_name.strip(),
                                       bank_account=bank_account, ifsc=ifsc)
        db.add(profile)
    old_bank = None if created else (profile.bank_account, profile.ifsc, profile.account_name)
    bank_changed = created or old_bank != (bank_account, ifsc, account_name.strip())
    profile.pan, profile.tds_section, profile.payee_type, profile.j_kind = pan, tds_section, payee_type, j_kind
    profile.account_name, profile.bank_account, profile.ifsc = account_name.strip(), bank_account, ifsc
    if bank_changed:
        # Maker-checker: new bank details are unusable until someone else verifies them.
        profile.status, profile.changed_by, profile.changed_at = "pending_verification", user.id, datetime.now(UTC)
        profile.verified_by = profile.verified_at = None
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="vendor_payment_profile", entity_id=profile.id, actor_id=user.id,
                 action="bank_details_changed" if bank_changed else "payment_profile_updated",
                 payload={"vendor_id": vendor_id, "account_old": _last4(old_bank[0]) if old_bank else None,
                          "account_new": _last4(bank_account), "ifsc": ifsc, "tds_section": tds_section,
                          "pan_on_file": pan is not None, "status": profile.status})
    return profile


def verify_profile(db: Session, user: User, vendor_id: uuid.UUID) -> VendorPaymentProfile:
    _require_role(user)
    profile = db.scalar(select(VendorPaymentProfile).where(VendorPaymentProfile.org_id == user.org_id,
                                                           VendorPaymentProfile.vendor_id == vendor_id).with_for_update())
    if profile is None:
        raise NotFound("This vendor has no payment details yet.")
    if profile.status == "verified":
        raise Conflict("These bank details are already verified.")
    if profile.changed_by == user.id:
        raise Forbidden("You changed these bank details, so someone else must verify them.")
    profile.status, profile.verified_by, profile.verified_at = "verified", user.id, datetime.now(UTC)
    record_event(db, org_id=user.org_id, entity_type="vendor_payment_profile", entity_id=profile.id, actor_id=user.id,
                 action="bank_details_verified", payload={"vendor_id": vendor_id, "account": _last4(profile.bank_account)})
    return profile


def profiles_view(db: Session, user: User) -> list[dict[str, Any]]:
    _require_role(user)
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    profiles = {p.vendor_id: p for p in db.scalars(select(VendorPaymentProfile)
                                                   .where(VendorPaymentProfile.org_id == user.org_id))}
    out = []
    for v in db.scalars(select(Vendor).where(Vendor.org_id == user.org_id).order_by(Vendor.name)):
        p = profiles.get(v.id)
        out.append({"vendor_id": v.id, "vendor": v.name, "gstin": v.gstin, "profile": None if p is None else {
            "pan": p.pan, "tds_section": p.tds_section, "payee_type": p.payee_type, "j_kind": p.j_kind,
            "account_name": p.account_name, "bank_account_last4": _last4(p.bank_account), "ifsc": p.ifsc,
            "status": p.status, "changed_by": names.get(p.changed_by), "changed_at": p.changed_at,
            "verified_by": names.get(p.verified_by), "can_verify": p.status != "verified" and p.changed_by != user.id}})
    return out


# --- Building a run ------------------------------------------------------------------------------------------

def _already_paid(db: Session, invoice_id: uuid.UUID, exclude_run: uuid.UUID | None = None) -> Decimal:
    query = (select(func.coalesce(func.sum(PaymentLine.gross), 0)).join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
             .where(PaymentLine.invoice_id == invoice_id, PaymentLine.status.in_(LIVE_LINE),
                    PaymentRun.status.in_(LIVE_RUN)))
    if exclude_run:
        query = query.where(PaymentLine.run_id != exclude_run)
    return Decimal(db.scalar(query))


def _tds_paid_before(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID | None, section: str | None,
                     fy: str, exclude_line: uuid.UUID | None = None) -> Decimal:
    """Base of earlier live payments to this vendor under this section in the financial year."""
    if vendor_id is None or section is None:
        return ZERO
    rows = db.execute(select(PaymentLine.tds_base, Invoice.invoice_date)
                      .join(Invoice, Invoice.id == PaymentLine.invoice_id)
                      .join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
                      .where(PaymentLine.org_id == org_id, PaymentLine.vendor_id == vendor_id,
                             PaymentLine.tds_section == section, PaymentLine.status.in_(LIVE_LINE),
                             PaymentRun.status.in_(LIVE_RUN), PaymentLine.id != exclude_line)).all()
    return sum((base for base, day in rows if day and fiscal_year(day) == fy), ZERO)


def _shared_account(db: Session, profile: VendorPaymentProfile) -> bool:
    return db.scalar(select(func.count()).select_from(VendorPaymentProfile).where(
        VendorPaymentProfile.org_id == profile.org_id, VendorPaymentProfile.bank_account == profile.bank_account,
        VendorPaymentProfile.ifsc == profile.ifsc, VendorPaymentProfile.vendor_id != profile.vendor_id)) > 0


def _first_payment(db: Session, vendor_id: uuid.UUID | None, exclude_run: uuid.UUID) -> bool:
    if vendor_id is None:
        return True
    return db.scalar(select(func.count()).select_from(PaymentLine).where(
        PaymentLine.vendor_id == vendor_id, PaymentLine.status == "paid", PaymentLine.run_id != exclude_run)) == 0


# Step 27 plugs the GSTR-2B check in here without this module importing it: fn(db, invoice) -> bool | None.
GSTR2B_CHECK: list = []


def assess(db: Session, invoice: Invoice, run_id: uuid.UUID, line_id: uuid.UUID | None = None) -> dict[str, Any]:
    """TDS and risk for paying what is left on `invoice` in run `run_id`. Pure rules, current facts."""
    already = _already_paid(db, invoice.id, exclude_run=run_id)
    gross = (invoice.total or ZERO) - already
    profile = profile_for(db, invoice.org_id, invoice.vendor_id) if invoice.vendor_id else None
    # TDS on the value before GST, in proportion when part of the invoice was paid earlier.
    total = invoice.total or ZERO
    base = ((invoice.subtotal or ZERO) * gross / total).quantize(Decimal("0.01")) if total else ZERO
    fy = fiscal_year(invoice.invoice_date) if invoice.invoice_date else ""
    section = profile.tds_section if profile else None
    result = compute_tds(TdsInput(section=section, payee_type=profile.payee_type if profile else "company",
                                  pan=profile.pan if profile else None, base=base,
                                  paid_before_in_fy=_tds_paid_before(db, invoice.org_id, invoice.vendor_id, section, fy,
                                                                     exclude_line=line_id),
                                  j_kind=profile.j_kind if profile else "professional"))
    bill = db.scalar(select(ErpOutbox.state).where(ErpOutbox.invoice_id == invoice.id))
    gstr2b = GSTR2B_CHECK[0](db, invoice) if GSTR2B_CHECK else None
    risks = check_payment(PaymentFacts(
        invoice_status=invoice.status, invoice_total=total, already_paid=already, gross=gross,
        has_profile=profile is not None, bank_verified=bool(profile and profile.status == "verified"),
        bank_changed_at=profile.changed_at if profile else None,
        bank_shared_with_other_vendor=bool(profile and _shared_account(db, profile)),
        tds_section=section, pan=profile.pan if profile else None,
        first_payment=_first_payment(db, invoice.vendor_id, run_id), bill_confirmed_in_erp=bill == "CONFIRMED",
        missing_from_gstr2b=gstr2b, now=datetime.now(UTC)))
    from app.modules.suppliers.service import hold_reason_for_vendor  # local import, as in erp_outbox/po.py

    supplier_hold = hold_reason_for_vendor(db, invoice.org_id, invoice.vendor_id)
    if supplier_hold:
        # §6e: a critical-risk supplier is not paid until a named reviewer clears the hold.
        risks = [*risks, {"code": "SUPPLIER_RISK_HOLD", "level": "block", "message": supplier_hold}]
    return {"gross": gross, "tds_base": result.taxable, "tds_section": result.section, "tds_rate": result.rate,
            "tds_amount": result.tds, "tds_reason": result.reason, "net": gross - result.tds, "risk_results": risks}


def eligible_invoices(db: Session, user: User) -> list[dict[str, Any]]:
    """Approved invoices with something left to pay."""
    _require_role(user)
    out = []
    for invoice in db.scalars(select(Invoice).where(Invoice.org_id == user.org_id, Invoice.status == "approved")
                              .order_by(Invoice.invoice_date)):
        left = (invoice.total or ZERO) - _already_paid(db, invoice.id)
        if left > 0:
            out.append({"invoice_id": invoice.id, "invoice_no": invoice.invoice_no, "vendor": invoice.vendor_name,
                        "invoice_date": invoice.invoice_date, "total": invoice.total, "left_to_pay": left})
    return out


def _load_run(db: Session, user: User, run_id: uuid.UUID, *, lock: bool = False) -> PaymentRun:
    _require_role(user)
    query = select(PaymentRun).where(PaymentRun.id == run_id, PaymentRun.org_id == user.org_id)
    run = db.scalar(query.with_for_update() if lock else query)
    if run is None:
        raise NotFound("Payment run not found.")
    return run


def _lines(db: Session, run: PaymentRun) -> list[PaymentLine]:
    return list(db.scalars(select(PaymentLine).where(PaymentLine.run_id == run.id, PaymentLine.status != "removed")
                           .order_by(PaymentLine.created_at)))


def _retotal(db: Session, run: PaymentRun) -> None:
    lines = _lines(db, run)
    run.total_gross = sum((ln.gross for ln in lines), ZERO)
    run.total_tds = sum((ln.tds_amount for ln in lines), ZERO)
    run.total_net = sum((ln.net for ln in lines), ZERO)


def _audit(db: Session, run: PaymentRun, user: User | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=run.org_id, entity_type="payment_run", entity_id=run.id,
                 actor_id=user.id if user else None, action=action, payload=payload or {})


def create_run(db: Session, user: User) -> PaymentRun:
    _require_role(user)
    number = (db.scalar(select(func.max(PaymentRun.number)).where(PaymentRun.org_id == user.org_id)) or 0) + 1
    run = PaymentRun(id=uuid.uuid4(), org_id=user.org_id, number=number, prepared_by=user.id)
    db.add(run)
    db.flush()
    _audit(db, run, user, "run_created")
    return run


def add_invoice(db: Session, user: User, run_id: uuid.UUID, invoice_id: uuid.UUID) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    if run.status != "draft":
        raise Conflict("Invoices can be added only while the run is a draft.")
    if run.prepared_by != user.id:
        raise Forbidden("Only the person preparing this run can change it.")
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == user.org_id).with_for_update())
    if invoice is None:
        raise NotFound("Invoice not found.")
    if db.scalar(select(PaymentLine.id).where(PaymentLine.run_id == run.id, PaymentLine.invoice_id == invoice.id,
                                              PaymentLine.status != "removed")):
        raise Conflict("This invoice is already in this run.")
    a = assess(db, invoice, run.id)
    line = PaymentLine(org_id=run.org_id, run_id=run.id, invoice_id=invoice.id, vendor_id=invoice.vendor_id,
                       gross=a["gross"], tds_base=a["tds_base"], tds_section=a["tds_section"], tds_rate=a["tds_rate"],
                       tds_amount=a["tds_amount"], net=a["net"], risk_results=a["risk_results"],
                       risk_rule_set_version=PAYMENT_RULE_SET_VERSION, tds_rule_set_version=TDS_RULE_SET_VERSION)
    db.add(line)
    db.flush()
    _retotal(db, run)
    _audit(db, run, user, "invoice_added", {"invoice_id": invoice.id, "gross": a["gross"], "tds": a["tds_amount"],
                                            "net": a["net"], "risk": [r["code"] for r in a["risk_results"]]})
    return run


def remove_line(db: Session, user: User, run_id: uuid.UUID, line_id: uuid.UUID) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    if run.status != "draft" or run.prepared_by != user.id:
        raise Conflict("Only the preparer can remove invoices, while the run is a draft.")
    line = db.scalar(select(PaymentLine).where(PaymentLine.id == line_id, PaymentLine.run_id == run.id))
    if line is None:
        raise NotFound("Line not found.")
    line.status = "removed"
    _retotal(db, run)
    _audit(db, run, user, "invoice_removed", {"invoice_id": line.invoice_id})
    return run


def _refresh_risk(db: Session, run: PaymentRun) -> list[PaymentLine]:
    """Re-run the rules on current facts: a bank change since the line was added must count."""
    lines = _lines(db, run)
    for line in lines:
        invoice = db.get(Invoice, line.invoice_id)
        a = assess(db, invoice, run.id, line.id)
        line.risk_results = a["risk_results"]
    return lines


def submit_run(db: Session, user: User, run_id: uuid.UUID) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    if run.status != "draft":
        raise Conflict("Only a draft run can be submitted.")
    if run.prepared_by != user.id:
        raise Forbidden("Only the person who prepared this run can submit it.")
    lines = _refresh_risk(db, run)
    if not lines:
        raise Conflict("Add at least one invoice first.")
    blocked = [r["message"] for ln in lines for r in ln.risk_results if r["level"] == "block"]
    if blocked:
        raise Conflict("Cannot submit: " + " ".join(sorted(set(blocked))))
    run.status = "submitted"
    _audit(db, run, user, "run_submitted", {"total_net": run.total_net, "lines": len(lines)})
    return run


def approval_refusal(db: Session, user: User, run: PaymentRun) -> Forbidden | Conflict | None:
    if user.role not in PAYMENT_ROLES:
        return Forbidden("Only finance or an admin can approve payments.")
    if run.status != "submitted":
        return Conflict("This run is not waiting for approval.")
    if run.prepared_by == user.id:
        return Forbidden("You prepared this run, so someone else must approve it.")
    invoice_ids = [ln.invoice_id for ln in _lines(db, run)]
    if invoice_ids and db.scalar(select(ReviewDecision.id).where(
            ReviewDecision.invoice_id.in_(invoice_ids), ReviewDecision.reviewer_id == user.id,
            ReviewDecision.decision == "approve").limit(1)):
        return Forbidden("You approved one of these invoices, so someone else must approve its payment.")
    from app.modules.close.service import IST, locked_refusal  # close imports bank, which imports nothing here

    locked = locked_refusal(db, run.org_id, datetime.now(IST).date(), "payments")
    if locked:
        return locked
    if run.total_net > user.approval_limit:
        return Forbidden(f"{rupees(run.total_net)} is above your approval limit of {rupees(user.approval_limit)}.")
    return None


def approve_run(db: Session, user: User, run_id: uuid.UUID, reason: str | None) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    refusal = approval_refusal(db, user, run)
    if refusal:
        raise refusal
    lines = _refresh_risk(db, run)
    if any(has_block(ln.risk_results) for ln in lines):
        raise Conflict("A blocking risk appeared since submission. Return the run to draft and fix it.")
    open_holds = sorted({r["code"] for ln in lines for r in holds(ln.risk_results)})
    reason = (reason or "").strip() or None
    if open_holds and not reason:
        raise Invalid(f"Give a reason to pay despite: {', '.join(open_holds)}.")
    run.status, run.approved_by, run.approved_at, run.hold_reason = "approved", user.id, datetime.now(UTC), reason
    run.bank_file_sha256 = hashlib.sha256(bank_file(db, run).encode("utf-8")).hexdigest()
    _audit(db, run, user, "run_approved", {"total_net": run.total_net, "holds_accepted": open_holds, "reason": reason,
                                           "bank_file_sha256": run.bank_file_sha256})
    return run


def cancel_run(db: Session, user: User, run_id: uuid.UUID) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    if run.status not in ("draft", "submitted", "approved"):
        raise Conflict("A run sent to the bank cannot be cancelled.")
    run.status = "cancelled"
    _audit(db, run, user, "run_cancelled")
    return run


# --- Bank file and the mock bank -----------------------------------------------------------------------------

def bank_file(db: Session, run: PaymentRun) -> str:
    """A generic NEFT/RTGS bulk upload file. Each bank has its own layout; this one is illustrative."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Payment Type", "Beneficiary Name", "Beneficiary Account", "IFSC", "Amount",
                     "Debit Narration", "Credit Narration"])
    for line in _lines(db, run):
        profile = profile_for(db, run.org_id, line.vendor_id) if line.vendor_id else None
        invoice = db.get(Invoice, line.invoice_id)
        writer.writerow(["RTGS" if line.net >= RTGS_FROM else "NEFT", csv_safe(profile.account_name if profile else ""),
                         profile.bank_account if profile else "", profile.ifsc if profile else "", f"{line.net:.2f}",
                         csv_safe(f"{run_label(run)} {invoice.invoice_no}"), csv_safe(f"Inv {invoice.invoice_no}"[:30])])
    return out.getvalue()


def download_bank_file(db: Session, user: User, run_id: uuid.UUID) -> tuple[str, str]:
    run = _load_run(db, user, run_id)
    if run.status not in ("approved", "sent", "settled", "partly_failed"):
        raise Conflict("The bank file exists once the run is approved.")
    text = bank_file(db, run)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != run.bank_file_sha256:
        raise Conflict("The bank file no longer matches what was approved. Do not upload it; ask an admin.")
    _audit(db, run, user, "bank_file_downloaded", {"bank_file_sha256": run.bank_file_sha256})
    return f"{run_label(run)}-bank-file.csv", text


def send_to_bank(db: Session, user: User, run_id: uuid.UUID) -> PaymentRun:
    run = _load_run(db, user, run_id, lock=True)
    if run.status != "approved":
        raise Conflict("Only an approved run can be sent.")
    run.status, run.sent_at = "sent", datetime.now(UTC)
    enqueue(db, org_id=run.org_id, kind="bank_settle", payload={"run_id": str(run.id)}, created_by=user.id)
    _audit(db, run, user, "sent_to_mock_bank", {"total_net": run.total_net})
    return run


def statement_key(run: PaymentRun) -> str:
    return f"{run.org_id}/bank-statements/{run_label(run)}.csv"


def _utr(run: PaymentRun, line: PaymentLine) -> str:
    digest = hashlib.sha256(f"{run.id}|{line.id}".encode()).hexdigest()[:10].upper()
    return f"SIMN{datetime.now(UTC):%y%m%d}{digest}"


@handler("bank_settle")
def settle(db: Session, job: Job) -> dict[str, Any]:
    """The mock bank: pays every line of a sent run once. Re-running it is a no-op."""
    run = db.scalar(select(PaymentRun).where(PaymentRun.id == uuid.UUID(job.payload["run_id"])).with_for_update())
    if run is None or run.status != "sent":
        return {"skipped": True}
    now = datetime.now(UTC)
    statement = io.StringIO()
    writer = csv.writer(statement, lineterminator="\n")
    writer.writerow(["Date", "Narration", "Reference", "Debit", "Credit", "Balance"])
    paid = failed = 0
    for line in _lines(db, run):
        profile = profile_for(db, run.org_id, line.vendor_id) if line.vendor_id else None
        invoice = db.get(Invoice, line.invoice_id)
        if profile is None or profile.ifsc == MOCK_BANK_INVALID_IFSC:
            line.status, line.failure_reason = "failed", "Account details invalid (returned by the bank)."
            failed += 1
            continue
        line.status, line.utr, line.paid_at = "paid", _utr(run, line), now
        paid += 1
        writer.writerow([f"{now:%Y-%m-%d}", csv_safe(f"{'RTGS' if line.net >= RTGS_FROM else 'NEFT'}/{profile.account_name}/"
                         f"{invoice.invoice_no}"), line.utr, f"{line.net:.2f}", "", ""])
    run.status = "settled" if failed == 0 else "partly_failed"
    run.settled_at = now
    get_file_store().put(statement_key(run), statement.getvalue().encode("utf-8"))
    _audit(db, run, None, "mock_bank_settled", {"paid": paid, "failed": failed})
    return {"paid": paid, "failed": failed}


def bank_statement(db: Session, user: User, run_id: uuid.UUID) -> tuple[str, bytes]:
    run = _load_run(db, user, run_id)
    if run.status not in ("settled", "partly_failed"):
        raise Conflict("The mock bank has not settled this run yet.")
    return f"{run_label(run)}-bank-statement.csv", get_file_store().get(statement_key(run))


# --- Views -------------------------------------------------------------------------------------------------

def run_view(db: Session, user: User, run: PaymentRun) -> dict[str, Any]:
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == run.org_id)).all())
    lines = []
    for ln in _lines(db, run):
        invoice = db.get(Invoice, ln.invoice_id)
        lines.append({"id": ln.id, "invoice_id": ln.invoice_id, "invoice_no": invoice.invoice_no,
                      "vendor": invoice.vendor_name, "gross": ln.gross, "tds_section": ln.tds_section,
                      "tds_rate": ln.tds_rate, "tds_amount": ln.tds_amount, "net": ln.net, "risk": ln.risk_results,
                      "status": ln.status, "utr": ln.utr, "failure_reason": ln.failure_reason})
    refusal = approval_refusal(db, user, run) if run.status == "submitted" else None
    return {"id": run.id, "label": run_label(run), "status": run.status, "prepared_by": names.get(run.prepared_by),
            "approved_by": names.get(run.approved_by), "approved_at": run.approved_at, "hold_reason": run.hold_reason,
            "total_gross": run.total_gross, "total_tds": run.total_tds, "total_net": run.total_net,
            "sent_at": run.sent_at, "settled_at": run.settled_at, "lines": lines,
            "holds": sorted({r["code"] for ln in lines for r in ln["risk"] if r["level"] == "hold"}),
            "blocks": sorted({r["code"] for ln in lines for r in ln["risk"] if r["level"] == "block"}),
            "allowed": {"edit": run.status == "draft" and run.prepared_by == user.id,
                        "submit": run.status == "draft" and run.prepared_by == user.id,
                        "approve": run.status == "submitted" and refusal is None,
                        "approve_blocked_reason": refusal.message if refusal else None,
                        "send": run.status == "approved",
                        "cancel": run.status in ("draft", "submitted", "approved")}}


def runs_view(db: Session, user: User) -> list[dict[str, Any]]:
    _require_role(user)
    names = dict(db.execute(select(User.id, User.full_name).where(User.org_id == user.org_id)).all())
    return [{"id": r.id, "label": run_label(r), "status": r.status, "total_net": r.total_net, "total_tds": r.total_tds,
             "prepared_by": names.get(r.prepared_by), "approved_by": names.get(r.approved_by), "created_at": r.created_at}
            for r in db.scalars(select(PaymentRun).where(PaymentRun.org_id == user.org_id)
                                .order_by(PaymentRun.number.desc()))]


def payments_section(db: Session, scope: Any, start: Any) -> dict[str, Any] | None:
    """Dashboard numbers (insights SECTION_PROVIDERS)."""
    if scope.role not in PAYMENT_ROLES:
        return None
    due = sum((((i.total or ZERO) - _already_paid(db, i.id)) for i in db.scalars(
        select(Invoice).where(Invoice.org_id == scope.org_id, Invoice.status == "approved"))), ZERO)
    by_status: dict[str, Decimal] = defaultdict(lambda: ZERO)
    tds = held = ZERO
    for line, run in db.execute(select(PaymentLine, PaymentRun).join(PaymentRun, PaymentRun.id == PaymentLine.run_id)
                                .where(PaymentLine.org_id == scope.org_id, PaymentLine.status != "removed",
                                       PaymentRun.status != "cancelled")).all():
        if line.status == "paid" and (start is None or (line.paid_at and line.paid_at >= start)):
            by_status["paid"] += line.net
            tds += line.tds_amount
        elif line.status == "pending":
            by_status["in_runs"] += line.net
            if run.status in ("draft", "submitted") and line.risk_results:
                held += line.gross
        elif line.status == "failed":
            by_status["failed"] += line.net
    return {"due": due, "in_runs": by_status["in_runs"], "paid": by_status["paid"], "failed": by_status["failed"],
            "held_by_risk": held, "tds_deducted": tds}
