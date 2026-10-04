"""Invoice intake: upload → extract job → review and edit → confirm (BUILD_PLAN §7; PROMPTS Step 7).

Statuses: extracting → needs_review | manual_entry (AI unavailable after 3 tries) → confirmed
→ (Step 8) matching → matched | exception → (Step 9) approved | rejected | correction_requested.
Every state change and every field edit writes its audit event in the same transaction, and
every edit is also kept in field_edits (old → new), because it matters for segregation of
duties later: whoever uploaded or edited an invoice may not approve its exception (§9).
"""

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.jobs import enqueue, handler
from app.models import Document, Extraction, FieldEdit, Invoice, InvoiceLine, Job, User
from app.modules.audit.service import record_event
from app.modules.invoices.providers import get_extractor, get_file_store
from app.modules.invoices.validation import (
    InvoiceFields,
    Issue,
    LineFields,
    fiscal_year,
    normalize_invoice_no,
    parse_date,
    parse_money,
    validate,
)
from app.ports.extractor import ExtractionResult

VIEW_ROLES = ("buyer", "approver", "finance", "admin")
WRITE_ROLES = ("finance", "admin")
EDITABLE_STATUSES = ("needs_review", "manual_entry", "correction_requested")
TEXT_FIELDS = ("vendor_name", "vendor_gstin", "buyer_gstin", "invoice_no", "po_reference", "place_of_supply")
MONEY_FIELDS = ("subtotal", "cgst", "sgst", "igst", "total")
LINE_ATTRS = ("description", "item_code", "hsn", "qty", "rate", "amount")


def _audit(db: Session, invoice: Invoice, actor_id: uuid.UUID | None, action: str, payload: dict | None = None) -> None:
    record_event(db, org_id=invoice.org_id, entity_type="invoice", entity_id=invoice.id, actor_id=actor_id,
                 action=action, payload={"status": invoice.status, **(payload or {})})


def _require_writer(user: User) -> None:
    if user.role not in WRITE_ROLES:
        raise Forbidden("Only finance or an admin can upload and confirm invoices.")


def load_invoice(db: Session, user: User, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
    query = select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == user.org_id)
    if lock:
        query = query.with_for_update()
    invoice = db.scalar(query)
    if invoice is None or user.role not in VIEW_ROLES:
        raise NotFound("Invoice not found.")
    return invoice


def invoice_lines(db: Session, invoice: Invoice) -> list[InvoiceLine]:
    return list(db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)))


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def fields_of(db: Session, invoice: Invoice) -> InvoiceFields:
    return InvoiceFields(
        vendor_gstin=invoice.vendor_gstin, buyer_gstin=invoice.buyer_gstin, invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        po_reference=invoice.po_reference,
        lines=[LineFields(l.description, l.item_code, l.hsn, _text(l.qty), _text(l.rate), _text(l.amount))
               for l in invoice_lines(db, invoice)],
        **{name: _text(getattr(invoice, name)) for name in MONEY_FIELDS},
    )


def issues_of(db: Session, invoice: Invoice) -> list[Issue]:
    return validate(fields_of(db, invoice), date.today())


def _derive_keys(invoice: Invoice) -> None:
    """Duplicate-key parts (§5): normalised number and Indian fiscal year."""
    invoice.invoice_no_norm = normalize_invoice_no(invoice.invoice_no) if invoice.invoice_no else None
    invoice.fiscal_year = fiscal_year(invoice.invoice_date) if invoice.invoice_date else None


# --- Upload --------------------------------------------------------------------------------------

def upload(db: Session, user: User, *, filename: str, content_type: str, data: bytes) -> Invoice:
    """Store the PDF, create the invoice and queue its extraction, in one transaction (caller commits)."""
    _require_writer(user)
    if len(data) > get_settings().max_upload_bytes:
        raise Invalid("The file is larger than 10 MB.")
    # §9: PDF only, content type checked; the first bytes must really be a PDF, whatever the name says.
    if content_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise Invalid("Only PDF invoices can be uploaded.")
    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Invoice.id).join(Document, Document.id == Invoice.document_id)
                         .where(Document.org_id == user.org_id, Document.sha256 == sha256))
    if existing:
        # §6 rule 9: the same file uploaded again is a blocking duplicate.
        raise Conflict(f"This exact file was already uploaded (invoice {existing}). Duplicate blocked.")
    key = f"{user.org_id}/{sha256}.pdf"
    get_file_store().put(key, data)
    document = Document(org_id=user.org_id, s3_key=key, sha256=sha256, filename=filename[:255] or "invoice.pdf",
                        content_type=content_type, size_bytes=len(data), uploaded_by=user.id)
    db.add(document)
    db.flush()
    invoice = Invoice(id=uuid.uuid4(), org_id=user.org_id, document_id=document.id, status="extracting")
    db.add(invoice)
    db.flush()
    _audit(db, invoice, user.id, "uploaded", {"filename": document.filename, "sha256": sha256, "bytes": len(data)})
    enqueue(db, org_id=user.org_id, kind="extract", payload={"invoice_id": str(invoice.id)}, created_by=user.id)
    return invoice


# --- Extraction job ------------------------------------------------------------------------------

def _apply_extraction(db: Session, invoice: Invoice, result: ExtractionResult, started: datetime) -> None:
    data = result.invoice
    for name in TEXT_FIELDS:
        value = getattr(data, name)
        setattr(invoice, name, value.strip() if isinstance(value, str) else value)
    invoice.invoice_date = parse_date(data.invoice_date)
    invoice.currency = data.currency or "INR"
    for name in MONEY_FIELDS:
        # A value the model wrote in an odd format is left empty and flagged for the reviewer.
        setattr(invoice, name, parse_money(getattr(data, name)))
    _derive_keys(invoice)
    for old in invoice_lines(db, invoice):
        db.delete(old)
    db.flush()
    for n, line in enumerate(data.lines, start=1):
        db.add(InvoiceLine(org_id=invoice.org_id, invoice_id=invoice.id, line_no=n, description=line.description,
                           item_code=line.item_code, hsn=line.hsn, qty=parse_money(line.qty) or Decimal("0"),
                           rate=parse_money(line.rate) or Decimal("0"), amount=parse_money(line.amount) or Decimal("0")))
    db.add(Extraction(org_id=invoice.org_id, invoice_id=invoice.id, model_id=result.model_id,
                      prompt_version=result.prompt_version, raw_output=result.raw_output,
                      field_evidence={e.field: {"quote": e.quote, "page": e.page} for e in data.evidence},
                      started_at=started, finished_at=datetime.now(UTC)))
    invoice.status, invoice.extraction_error = "needs_review", None
    db.flush()
    _audit(db, invoice, None, "extracted", {
        "model_id": result.model_id, "prompt_version": result.prompt_version, "confidence": data.confidence,
        "issues": [i.code for i in issues_of(db, invoice)]})


def _extraction_gave_up(db: Session, job: Job, error: str) -> None:
    invoice = db.get(Invoice, uuid.UUID(job.payload["invoice_id"]), with_for_update=True)
    if invoice is None or invoice.status != "extracting":
        return
    invoice.status, invoice.extraction_error = "manual_entry", error
    _audit(db, invoice, None, "extraction_failed", {"error": error, "attempts": job.attempts})


@handler("extract", on_give_up=_extraction_gave_up)
def run_extraction(db: Session, job: Job) -> dict[str, Any]:
    invoice = db.get(Invoice, uuid.UUID(job.payload["invoice_id"]), with_for_update=True)
    if invoice is None or invoice.status != "extracting":
        # Already done (e.g. a re-run after a worker crash): nothing to do.
        return {"skipped": invoice.status if invoice else "missing"}
    document = db.get(Document, invoice.document_id)
    started = datetime.now(UTC)
    result = get_extractor().extract(get_file_store().get(document.s3_key))
    _apply_extraction(db, invoice, result, started)
    return {"model_id": result.model_id, "lines": len(result.invoice.lines)}


# --- Review: edits and confirmation --------------------------------------------------------------

def _record(db: Session, invoice: Invoice, user: User, field: str, old: Any, new: Any, changes: list[str]) -> None:
    old_text, new_text = _text(old), _text(new)
    if old_text == new_text:
        return
    db.add(FieldEdit(org_id=invoice.org_id, invoice_id=invoice.id, field=field, old=old_text, new=new_text,
                     edited_by=user.id))
    changes.append(field)


def _money_input(name: str, value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = parse_money(value)
    if parsed is None:
        raise Invalid(f"{name}: enter a plain number such as 54870.00 (no commas or ₹).")
    return parsed


def edit_fields(db: Session, user: User, invoice_id: uuid.UUID, *, fields: dict[str, str | None],
                lines: list[dict[str, str | None]] | None) -> Invoice:
    """Correct extracted values. Each changed value becomes a field_edits row; one audit event per save."""
    _require_writer(user)
    invoice = load_invoice(db, user, invoice_id, lock=True)
    if invoice.status not in EDITABLE_STATUSES:
        raise Conflict("This invoice can no longer be edited.")
    changes: list[str] = []
    for name, value in fields.items():
        value = value.strip() if isinstance(value, str) else value
        if name in TEXT_FIELDS:
            new = value or None
        elif name in MONEY_FIELDS:
            new = _money_input(name, value)
        elif name == "invoice_date":
            new = parse_date(value) if value else None
            if value and new is None:
                raise Invalid("invoice_date: use a real date in the form YYYY-MM-DD.")
        else:
            raise Invalid(f"{name} cannot be edited.")
        _record(db, invoice, user, name, getattr(invoice, name), new, changes)
        setattr(invoice, name, new)
    if lines is not None:
        current = invoice_lines(db, invoice)
        if len(lines) != len(current):
            _record(db, invoice, user, "lines", f"{len(current)} lines", f"{len(lines)} lines", changes)
        for n, line in enumerate(lines, start=1):
            old = current[n - 1] if n <= len(current) else None
            values = {
                "description": (line.get("description") or "").strip(),
                "item_code": (line.get("item_code") or "").strip() or None,
                "hsn": (line.get("hsn") or "").strip() or None,
                **{attr: _money_input(f"line {n} {attr}", line.get(attr)) or Decimal("0") for attr in ("qty", "rate", "amount")},
            }
            if old is None:
                db.add(InvoiceLine(org_id=invoice.org_id, invoice_id=invoice.id, line_no=n, **values))
                continue
            for attr, new in values.items():
                _record(db, invoice, user, f"lines[{n}].{attr}", getattr(old, attr), new, changes)
                setattr(old, attr, new)
        for extra in current[len(lines):]:
            db.delete(extra)
    if not changes:
        return invoice
    _derive_keys(invoice)
    db.flush()
    _audit(db, invoice, user.id, "fields_edited", {"fields": changes})
    return invoice


def confirm(db: Session, user: User, invoice_id: uuid.UUID, *, acknowledge_issues: bool) -> Invoice:
    """The finance user confirms the fields. Open validation issues block this unless the user
    explicitly confirms the invoice "as printed", in which case matching will raise exceptions."""
    _require_writer(user)
    invoice = load_invoice(db, user, invoice_id, lock=True)
    if invoice.status not in EDITABLE_STATUSES:
        raise Conflict("Only an invoice waiting for review can be confirmed.")
    issues = issues_of(db, invoice)
    blocking = [i for i in issues if i.code in ("REQUIRED", "NOT_A_NUMBER", "DATE_INVALID")]
    if blocking:
        raise Invalid("Fill in: " + ", ".join(sorted({i.field for i in blocking})) + ".")
    if issues and not acknowledge_issues:
        raise Conflict("Some checks failed. Fix the highlighted fields, or confirm the invoice exactly as printed.")
    from app.modules.invoices.match_job import start_match  # local import: match_job imports this module

    invoice.status, invoice.confirmed_by, invoice.confirmed_at = "confirmed", user.id, datetime.now(UTC)
    _audit(db, invoice, user.id, "confirmed", {"acknowledged_issues": [i.code for i in issues]})
    # Step 8: confirmation queues the match in the same transaction (status becomes "matching").
    start_match(db, invoice, user.id)
    return invoice


def latest_extraction(db: Session, invoice: Invoice) -> Extraction | None:
    return db.scalar(select(Extraction).where(Extraction.invoice_id == invoice.id)
                     .order_by(Extraction.created_at.desc()).limit(1))


def edit_history(db: Session, invoice: Invoice) -> list[FieldEdit]:
    return list(db.scalars(select(FieldEdit).where(FieldEdit.invoice_id == invoice.id).order_by(FieldEdit.created_at)))
