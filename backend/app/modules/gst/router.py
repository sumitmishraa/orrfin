"""HTTP routes for GSTR-2B matching (BUILD_PLAN v2.4 change 34; PROMPTS Step 27). Matching only, no filing.

Importing this module registers the GSTR-2B hold in payments, the close checklist item and the dashboard
section, so those modules never import this one.
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.close.service import EXTRA_CHECKS
from app.modules.gst import service
from app.modules.insights.service import SECTION_PROVIDERS
from app.modules.payments.service import GSTR2B_CHECK

router = APIRouter(prefix="/gstr2b", tags=["gst"])


@router.get("")
def view(user: CurrentUser, db: DbSession, period: str | None = None) -> JSONResponse:
    return JSONResponse(to_jsonable(service.view(db, user, period)))


@router.post("", status_code=201)
def upload(user: CurrentUser, db: DbSession, file: UploadFile = File(...)) -> JSONResponse:
    data = file.file.read(service.MAX_BYTES + 1)
    imp = service.import_2b(db, user, file.filename or "gstr2b.json", data)
    db.commit()
    return JSONResponse(to_jsonable(service.view(db, user, imp.period)), status_code=201)


if not GSTR2B_CHECK:
    GSTR2B_CHECK.append(service.missing_from_2b)
if service.close_check not in EXTRA_CHECKS:
    EXTRA_CHECKS.append(service.close_check)
SECTION_PROVIDERS["gst"] = service.dashboard_section
