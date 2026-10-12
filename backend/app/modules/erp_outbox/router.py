"""HTTP routes for ERP write-back status and "Retry sync" (BUILD_PLAN §8 demo; PROMPTS Steps 14-15).

The invoice page gets its ERP sync block through the invoices module's DETAIL_EXTENSIONS hook, so the
invoices module never imports the outbox. Retry is open to finance, buyers and admins (the people who
approve invoices or own POs); the service enforces it.
"""

import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter
from app.auth.dependencies import CurrentUser, DbSession
from app.errors import Forbidden, NotFound
from app.models import ErpConnection, ErpOutbox, Invoice, User
from app.modules.erp_outbox import service
from app.modules.invoices.router import DETAIL_EXTENSIONS
from app.modules.invoices.schemas import InvoiceDetail

router = APIRouter(prefix="/erp-outbox", tags=["erp write-back"])


def _add_erp_sync(db: Session, user: User, invoice: Invoice, detail: InvoiceDetail) -> None:
    row = service.outbox_for(db, invoice_id=invoice.id)
    detail.erp_sync = service.status_for(db, row)
    if row is None and invoice.status == "approved":
        detail.erp_sync_note = service.bill_unavailable_reason(db, invoice)


DETAIL_EXTENSIONS.append(_add_erp_sync)


@router.get("/{outbox_id}/import-file")
def import_file(outbox_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FileResponse:
    """The import file a file-based ERP (BUSY) needs a person to load. Same roles as Retry sync."""
    if user.role not in service.RETRY_ROLES:
        raise Forbidden("Only finance, a buyer or an admin can download ERP import files.")
    row = db.get(ErpOutbox, outbox_id)
    if row is None or row.org_id != user.org_id or row.state != "CONFIRMED":
        raise NotFound("No import file for this document.")
    adapter = get_adapter(db.get(ErpConnection, row.erp_connection_id))
    if not hasattr(adapter, "import_file_path"):
        raise NotFound("This ERP takes drafts directly; there is no import file.")
    path = adapter.import_file_path(row.erp_doc_name)
    if not path.exists():
        raise NotFound("The import file is missing; use Retry sync to write it again.")
    return FileResponse(path, media_type="application/xml", filename=path.name)


@router.post("/{outbox_id}/retry")
def retry(outbox_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    result = service.retry(db, user, outbox_id)
    db.commit()
    return result
