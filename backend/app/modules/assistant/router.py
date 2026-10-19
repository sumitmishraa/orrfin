"""HTTP route for the Orrfin Assistant (BUILD_PLAN v2.3 change 25; ADR 0007).

The answer and the log row commit together; an unavailable model still leaves a log row,
so outages are visible. The route never changes any business record.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.assistant import drafts, service
from app.modules.audit.service import to_jsonable
from app.modules.invoices.providers import get_assistant, get_drafter
from app.ports.extractor import ExtractorUnavailable

router = APIRouter(prefix="/assistant", tags=["assistant"])
# Same module, paths outside /assistant (the invoice page and the dashboard call these).
notes_router = APIRouter(tags=["assistant"])


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class PageContext(BaseModel):
    type: Literal["request", "invoice"]
    id: str = Field(max_length=64)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)
    context: PageContext | None = None


@router.post("/ask")
def ask(body: AskIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    try:
        assistant = get_assistant()
    except ExtractorUnavailable:  # e.g. GEMINI_API_KEY not set
        assistant = None
    reply = service.ask(db, user, body.question, [h.model_dump() for h in body.history],
                        body.context.model_dump() if body.context else None, assistant)
    db.commit()
    return JSONResponse(to_jsonable(reply))


# --- Step 24: drafts and notes -------------------------------------------------------------------------

class DraftRequestIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)


class NoteIn(BaseModel):
    audience: Literal["vendor", "requester"] = "vendor"


def _drafter():
    try:
        return get_drafter()
    except ExtractorUnavailable:  # e.g. no API key
        return None


@router.post("/draft-request")
def draft_request(body: DraftRequestIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    """One sentence → a pre-filled request form. Nothing is saved: the requester checks and submits."""
    return JSONResponse(to_jsonable(drafts.draft_request(db, user, body.text, _drafter())))


@notes_router.post("/invoices/{invoice_id}/draft-note")
def draft_note(invoice_id: uuid.UUID, body: NoteIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    """A note to copy to the vendor or requester about a held invoice. Orrfin sends nothing."""
    return JSONResponse(to_jsonable(drafts.draft_note(db, user, invoice_id, body.audience, _drafter())))


@notes_router.post("/insights/notes")
def insights_notes(user: CurrentUser, db: DbSession,
                   period: Literal["month", "quarter"] = Query("month")) -> JSONResponse:
    """'What changed' bullets for the dashboard, from computed numbers only."""
    return JSONResponse(to_jsonable(drafts.flux_notes(db, user, period, _drafter())))
