"""ERP write-back outbox: draft bills and draft POs, exactly once in effect (BUILD_PLAN §8; PROMPTS Steps 14-15).

Generic over document type and ERP. It only talks to the ErpAdapter port (create_draft_* / find_*), so every
connector reuses it unchanged. The §8 protocol, step by step:

1. Approval → in the SAME transaction: an erp_outbox row (PENDING) keyed by the idempotency key, a job and an
   audit event. One row per document: approving twice can't create a second row (unique key).
2. The worker marks the row SENT and commits *before* calling the ERP, so a crash mid-call is visible.
3. Success → CONFIRMED with the ERP's document name.
4. A clear refusal (validation, permissions) → FAILED, shown to finance. Retrying won't help until fixed.
5. Timeout / 5xx / network → UNKNOWN. Every later attempt **looks the document up first**; found → CONFIRMED,
   not found → create again. A SENT row seen at the start of an attempt is treated like UNKNOWN.
"Retry sync" on a CONFIRMED row only looks up and reports "already in <ERP> as X, no duplicate created".
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter, label_for, spec_for
from app.errors import Conflict, Forbidden, NotFound
from app.jobs import enqueue, handler
from app.models import ErpConnection, ErpOutbox, Invoice, Job, PoLine, PurchaseOrder, User, Vendor
from app.modules.audit.service import record_event
from app.modules.connectors.service import safe_message
from app.modules.invoices.service import invoice_lines
from app.ports.erp import (
    Created,
    DraftBill,
    DraftLine,
    ErpAdapter,
    ErpError,
    ErpNotSupported,
    ErpRejected,
    ErpUnknown,
)
from app.security.outbound import UrlNotAllowed
from app.security.secrets import SecretsUnavailable

ENTITY = "erp_outbox"
RETRY_ROLES = ("finance", "admin", "buyer")
CONFIG_FAILURES = (LookupError, UrlNotAllowed, SecretsUnavailable)


def bill_key(invoice: Invoice) -> str:
    """§8 step 1: sha256(org_id|vendor_gstin|invoice_no_norm|fiscal_year)."""
    raw = f"{invoice.org_id}|{invoice.vendor_gstin or ''}|{invoice.invoice_no_norm or ''}|{invoice.fiscal_year or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _audit(db: Session, row: ErpOutbox, actor_id: uuid.UUID | None, action: str, payload: dict[str, Any]) -> None:
    record_event(db, org_id=row.org_id, entity_type=ENTITY, entity_id=row.id, actor_id=actor_id, action=action,
                 payload={"doc_type": row.doc_type, "state": row.state, **payload})


def _erp_name(db: Session, row: ErpOutbox) -> str:
    return spec_for(db.get(ErpConnection, row.erp_connection_id).system).name


# --- Bills (Step 14) ---------------------------------------------------------------------------------

def bill_unavailable_reason(db: Session, invoice: Invoice) -> str | None:
    """Why this approved invoice can't be drafted into the ERP, or None. Shown on the invoice page."""
    po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
    if po is None or po.vendor_id is None:
        return "No ERP purchase order is linked, so there is no ERP vendor to bill. Enter the bill in the ERP by hand."
    if (invoice.vat or 0) > 0:
        # The draft-bill contract carries Indian GST columns only; writing a VAT bill through it would
        # give the ERP a bill whose tax does not add up. VAT write-back arrives with the UAE connectors.
        return ("This invoice carries UAE VAT. Orrfin does not write VAT bills to the ERP yet; "
                "enter the bill in the ERP by hand.")
    connection = db.get(ErpConnection, po.erp_connection_id)
    if not connection.is_active:
        return (f"This invoice was matched against {spec_for(connection.system).name} ({connection.mode}), which is "
                "no longer the active ERP. Re-run the match, then approve again.")
    try:
        caps = get_adapter(connection).capabilities()
    except CONFIG_FAILURES as exc:
        return f"{spec_for(connection.system).name} isn't ready: {exc}"
    if not caps.can_write_bill:
        return caps.write_note or f"{spec_for(connection.system).name} can't hold draft bills from Orrfin."
    return None


def queue_bill(db: Session, invoice: Invoice, actor_id: uuid.UUID) -> ErpOutbox | None:
    """Called inside the approval transaction. Returns the row, or None (the page shows the reason)."""
    if bill_unavailable_reason(db, invoice):
        return None
    key = bill_key(invoice)
    existing = db.scalar(select(ErpOutbox).where(ErpOutbox.idempotency_key == key))
    if existing is not None:
        return existing
    po = db.get(PurchaseOrder, invoice.po_id)
    row = ErpOutbox(org_id=invoice.org_id, erp_connection_id=po.erp_connection_id, idempotency_key=key,
                    doc_type="purchase_invoice", invoice_id=invoice.id, state="PENDING")
    db.add(row)
    db.flush()
    enqueue(db, org_id=invoice.org_id, kind="erp_push", payload={"outbox_id": str(row.id)}, created_by=actor_id)
    _audit(db, row, actor_id, "erp_draft_queued", {"invoice_id": invoice.id, "erp": _erp_name(db, row)})
    return row


def build_draft_bill(db: Session, row: ErpOutbox) -> DraftBill:
    invoice = db.get(Invoice, row.invoice_id)
    po = db.get(PurchaseOrder, invoice.po_id)
    vendor = db.get(Vendor, po.vendor_id)
    po_lines = {line.id: line for line in db.scalars(select(PoLine).where(PoLine.po_id == po.id))}
    lines = []
    for line in invoice_lines(db, invoice):
        po_line = po_lines.get(line.po_line_id) if line.po_line_id else None
        lines.append(DraftLine(item_code=line.item_code or (po_line.item_code if po_line else ""),
                               description=line.description, hsn=line.hsn, qty=line.qty, rate=line.rate,
                               amount=line.amount, tax_rate=po_line.tax_rate if po_line else 0,
                               uom=po_line.uom if po_line else None,
                               po_line_ref=po_line.erp_ref if po_line else None))
    return DraftBill(idempotency_key=row.idempotency_key, vendor_ref=vendor.erp_ref, vendor_gstin=invoice.vendor_gstin,
                     supplier_invoice_no=invoice.invoice_no or "", invoice_date=invoice.invoice_date,
                     po_ref=po.erp_ref, currency=invoice.currency, lines=lines, net_total=invoice.subtotal or 0,
                     cgst=invoice.cgst or 0, sgst=invoice.sgst or 0, igst=invoice.igst or 0,
                     grand_total=invoice.total or 0)


# --- The push job (both document types) -------------------------------------------------------------------

def _lookup(db: Session, row: ErpOutbox, adapter: ErpAdapter) -> str | None:
    if row.doc_type == "purchase_invoice":
        bill = build_draft_bill(db, row)
        return adapter.find_bill(bill.vendor_ref, bill.supplier_invoice_no)
    return adapter.find_po(row.idempotency_key)


def _create(db: Session, row: ErpOutbox, adapter: ErpAdapter) -> Created:
    if row.doc_type == "purchase_invoice":
        return adapter.create_draft_bill(build_draft_bill(db, row))
    from app.modules.erp_outbox.po import build_draft_po

    return adapter.create_draft_po(build_draft_po(db, row))


def _confirm(db: Session, row: ErpOutbox, name: str, via: str, import_file: str | None = None) -> None:
    row.state, row.erp_doc_name, row.last_error = "CONFIRMED", name, None
    _audit(db, row, None, "erp_draft_confirmed", {"erp_doc_name": name, "via": via, "import_file": import_file})
    if row.doc_type == "purchase_order":
        from app.modules.erp_outbox.po import on_po_confirmed

        on_po_confirmed(db, row)


def _fail(db: Session, row: ErpOutbox, connection: ErpConnection, message: str) -> None:
    row.state, row.last_error = "FAILED", safe_message(connection, message)
    _audit(db, row, None, "erp_draft_failed", {"error": row.last_error})


@handler("erp_push")
def run_push(db: Session, job: Job) -> dict[str, Any]:
    row = db.scalar(select(ErpOutbox).where(ErpOutbox.id == uuid.UUID(job.payload["outbox_id"])).with_for_update())
    if row is None or row.state in ("CONFIRMED", "FAILED"):
        return {"skipped": row.state if row else "missing"}
    connection = db.get(ErpConnection, row.erp_connection_id)
    try:
        adapter = get_adapter(connection)
    except CONFIG_FAILURES as exc:
        _fail(db, row, connection, f"Can't reach {spec_for(connection.system).name}: {exc}")
        return {"state": row.state}

    # §8 step 5: after any earlier attempt (UNKNOWN, or SENT left by a crash), look up before creating.
    if row.state in ("UNKNOWN", "SENT") or row.attempts > 0:
        try:
            found = _lookup(db, row, adapter)
        except ErpUnknown as exc:
            row.state, row.last_error = "UNKNOWN", safe_message(connection, str(exc))
            db.commit()
            raise
        except ErpError as exc:
            _fail(db, row, connection, str(exc))
            return {"state": row.state}
        if found:
            _confirm(db, row, found, via="lookup")
            return {"state": row.state, "erp_doc_name": found, "via": "lookup"}

    row.state = "SENT"
    row.attempts += 1
    _audit(db, row, None, "erp_draft_sent", {"attempt": row.attempts})
    db.commit()  # SENT must survive a crash during the call (§8 step 2)
    row = db.scalar(select(ErpOutbox).where(ErpOutbox.id == row.id).with_for_update())
    try:
        created = _create(db, row, adapter)
    except ErpUnknown as exc:
        row.state, row.last_error = "UNKNOWN", safe_message(connection, str(exc))
        _audit(db, row, None, "erp_draft_unknown", {"error": row.last_error})
        db.commit()
        raise  # the job retries with backoff; the next attempt looks up first
    except (ErpRejected, ErpNotSupported) as exc:
        _fail(db, row, connection, str(exc))
        return {"state": row.state}
    _confirm(db, row, created.erp_doc_name, via="created", import_file=created.import_file)
    return {"state": row.state, "erp_doc_name": created.erp_doc_name}


# --- What the pages show, and "Retry sync" --------------------------------------------------------------

def status_for(db: Session, row: ErpOutbox | None) -> dict[str, Any] | None:
    if row is None:
        return None
    connection = db.get(ErpConnection, row.erp_connection_id)
    return {"id": str(row.id), "state": row.state, "erp_doc_name": row.erp_doc_name, "attempts": row.attempts,
            "last_error": row.last_error, "erp": spec_for(connection.system).name, "label": label_for(connection),
            "doc_type": row.doc_type,
            # File-based ERPs (BUSY): the draft is an import file the page offers for download.
            "import_file_url": f"/erp-outbox/{row.id}/import-file"
            if spec_for(connection.system).file_based and row.state == "CONFIRMED" else None}


def outbox_for(db: Session, *, invoice_id: uuid.UUID | None = None,
               request_id: uuid.UUID | None = None) -> ErpOutbox | None:
    if invoice_id is not None:
        return db.scalar(select(ErpOutbox).where(ErpOutbox.invoice_id == invoice_id))
    return db.scalar(select(ErpOutbox).where(ErpOutbox.request_id == request_id))


def retry(db: Session, user: User, outbox_id: uuid.UUID) -> dict[str, Any]:
    """'Retry sync'. CONFIRMED: look up only and report. Otherwise queue another push (which looks up first)."""
    if user.role not in RETRY_ROLES:
        raise Forbidden("Only finance, a buyer or an admin can retry an ERP sync.")
    row = db.scalar(select(ErpOutbox).where(ErpOutbox.id == outbox_id, ErpOutbox.org_id == user.org_id)
                    .with_for_update())
    if row is None:
        raise NotFound("Not found.")
    connection = db.get(ErpConnection, row.erp_connection_id)
    erp = spec_for(connection.system).name
    if row.state == "CONFIRMED":
        try:
            found = _lookup(db, row, get_adapter(connection))
        except (ErpError, *CONFIG_FAILURES) as exc:
            raise Conflict(f"Couldn't check {erp} right now: {safe_message(connection, str(exc))}") from None
        message = (f"Already in {erp} as {found}, no duplicate created." if found
                   else f"{erp} no longer shows {row.erp_doc_name}; it may have been deleted there.")
        _audit(db, row, user.id, "erp_retry_checked", {"found": found})
        return {"message": message, "status": status_for(db, row)}
    pending = db.scalar(select(Job.id).where(Job.kind == "erp_push", Job.status.in_(("queued", "running")),
                                             Job.payload["outbox_id"].astext == str(row.id)))
    if pending is None:
        if row.state == "FAILED":
            row.state = "UNKNOWN"  # a person fixed the cause in the ERP; look up first, then create
        enqueue(db, org_id=row.org_id, kind="erp_push", payload={"outbox_id": str(row.id)}, created_by=user.id)
        _audit(db, row, user.id, "erp_retry_requested", {})
    return {"message": f"Sync to {erp} queued. Orrfin looks the document up first, so no duplicate can be created.",
            "status": status_for(db, row)}
