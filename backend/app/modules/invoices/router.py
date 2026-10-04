"""HTTP routes for invoices: upload, review, edit, confirm, view the PDF (BUILD_PLAN §7, §9; PROMPTS Step 7).

Every query is filtered by the user's org. The PDF is served through the API after the same
org check, never from a public URL (§9 "files served through short-lived pre-signed URLs" on S3).
"""

import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.fake_extractor import FAKE_MODEL_ID
from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.config import get_settings
from app.models import Document, Invoice, MatchResult, User
from app.modules.audit.service import timeline
from app.modules.invoices import service
from app.modules.invoices.providers import get_file_store
from app.modules.invoices.schemas import (
    ConfirmIn,
    ExtractionOut,
    FieldEditOut,
    InvoiceAllowed,
    InvoiceDetail,
    InvoiceEdit,
    InvoiceLineOut,
    InvoiceSummary,
    IssueOut,
    TimelineEventOut,
)

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_roles(*service.VIEW_ROLES))])

# Hooks the later steps fill in (match details, decisions, allowed actions), so this router
# stays the single place that shapes an invoice for the screen.
DETAIL_EXTENSIONS: list = []


def _add_match(db: Session, user: User, invoice: Invoice, detail: InvoiceDetail) -> None:
    from app.modules.invoices.match_job import match_view

    detail.match = match_view(db, invoice)
    if detail.match:
        detail.outcome = detail.match["outcome"]  # "stale" when the ERP changed after matching


DETAIL_EXTENSIONS.append(_add_match)


def _latest_match(db: Session, invoice: Invoice) -> MatchResult | None:
    return db.scalar(select(MatchResult).where(MatchResult.invoice_id == invoice.id)
                     .order_by(MatchResult.created_at.desc()).limit(1))


def _summary(db: Session, invoice: Invoice, document: Document) -> InvoiceSummary:
    match = _latest_match(db, invoice)
    return InvoiceSummary(
        id=invoice.id, status=invoice.status, filename=document.filename, vendor_name=invoice.vendor_name,
        invoice_no=invoice.invoice_no, invoice_date=invoice.invoice_date, po_reference=invoice.po_reference,
        total=invoice.total, created_at=invoice.created_at,
        outcome=match.outcome if match else None, amount_at_risk=match.amount_at_risk if match else None,
        risk_score=match.risk_score if match else None)


def _name(db: Session, user_id: uuid.UUID | None) -> str | None:
    return db.scalar(select(User.full_name).where(User.id == user_id)) if user_id else None


def build_detail(db: Session, user: User, invoice: Invoice) -> InvoiceDetail:
    db.flush()
    document = db.get(Document, invoice.document_id)
    extraction = service.latest_extraction(db, invoice)
    is_writer = user.role in service.WRITE_ROLES
    editable = invoice.status in service.EDITABLE_STATUSES
    detail = InvoiceDetail(
        **_summary(db, invoice, document).model_dump(),
        vendor_gstin=invoice.vendor_gstin, buyer_gstin=invoice.buyer_gstin, place_of_supply=invoice.place_of_supply,
        currency=invoice.currency, subtotal=invoice.subtotal, cgst=invoice.cgst, sgst=invoice.sgst, igst=invoice.igst,
        uploaded_by_name=_name(db, document.uploaded_by) or "", confirmed_by_name=_name(db, invoice.confirmed_by),
        confirmed_at=invoice.confirmed_at, extraction_error=invoice.extraction_error,
        lines=[InvoiceLineOut(line_no=l.line_no, description=l.description, item_code=l.item_code, hsn=l.hsn,
                              qty=l.qty, rate=l.rate, amount=l.amount, po_line_id=l.po_line_id,
                              pairing_method=l.pairing_method) for l in service.invoice_lines(db, invoice)],
        issues=[IssueOut(field=i.field, code=i.code, message=i.message) for i in service.issues_of(db, invoice)]
        if invoice.status != "extracting" else [],
        evidence=dict(extraction.field_evidence) if extraction else {},
        extraction=ExtractionOut(model_id=extraction.model_id, prompt_version=extraction.prompt_version,
                                 confidence=(extraction.raw_output or {}).get("confidence"),
                                 finished_at=extraction.finished_at,
                                 simulated=extraction.model_id == FAKE_MODEL_ID) if extraction else None,
        edits=[FieldEditOut(field=e.field, old=e.old, new=e.new, edited_by_name=_name(db, e.edited_by) or "",
                            at=e.created_at) for e in service.edit_history(db, invoice)],
        timeline=[TimelineEventOut(**{k: v for k, v in e.items() if k != "hash"})
                  for e in timeline(db, invoice.org_id, invoice.id)],
        allowed=InvoiceAllowed(edit=is_writer and editable, confirm=is_writer and editable),
    )
    for extend in DETAIL_EXTENSIONS:
        extend(db, user, invoice, detail)
    return detail


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(user: CurrentUser, db: DbSession, scope: str = Query("all")) -> list[InvoiceSummary]:
    rows = db.execute(select(Invoice, Document).join(Document, Document.id == Invoice.document_id)
                      .where(Invoice.org_id == user.org_id).order_by(Invoice.created_at.desc())).all()
    summaries = [_summary(db, invoice, document) for invoice, document in rows]
    if scope == "exceptions":
        # Step 9 exception inbox: open exceptions first, largest ₹ at risk first.
        summaries = [s for s in summaries if s.status == "exception"]
        summaries.sort(key=lambda s: (s.amount_at_risk or 0, s.risk_score or 0), reverse=True)
    elif scope == "review":
        summaries = [s for s in summaries if s.status in service.EDITABLE_STATUSES or s.status == "extracting"]
    return summaries


@router.post("", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def upload_invoice(user: CurrentUser, db: DbSession, file: UploadFile = File(...)) -> InvoiceDetail:
    # Read one byte past the limit so an oversize file is detected without loading all of it.
    data = file.file.read(get_settings().max_upload_bytes + 1)
    invoice = service.upload(db, user, filename=file.filename or "invoice.pdf",
                             content_type=file.content_type or "", data=data)
    db.commit()
    return build_detail(db, user, invoice)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: uuid.UUID, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    return build_detail(db, user, service.load_invoice(db, user, invoice_id))


@router.get("/{invoice_id}/file")
def get_invoice_file(invoice_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    invoice = service.load_invoice(db, user, invoice_id)
    document = db.get(Document, invoice.document_id)
    return Response(get_file_store().get(document.s3_key), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{document.filename}"',
                             "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.patch("/{invoice_id}", response_model=InvoiceDetail)
def edit_invoice(invoice_id: uuid.UUID, body: InvoiceEdit, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    lines = [line.model_dump() for line in body.lines] if body.lines is not None else None
    invoice = service.edit_fields(db, user, invoice_id, fields=body.fields, lines=lines)
    db.commit()
    return build_detail(db, user, invoice)


@router.post("/{invoice_id}/confirm", response_model=InvoiceDetail)
def confirm_invoice(invoice_id: uuid.UUID, body: ConfirmIn, user: CurrentUser, db: DbSession) -> InvoiceDetail:
    invoice = service.confirm(db, user, invoice_id, acknowledge_issues=body.acknowledge_issues)
    db.commit()
    return build_detail(db, user, invoice)
