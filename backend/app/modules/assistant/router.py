"""HTTP route for the Orrfin Assistant (BUILD_PLAN v2.3 change 25; ADR 0007).

The answer and the log row commit together; an unavailable model still leaves a log row,
so outages are visible. The route never changes any business record.
"""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.assistant import service
from app.modules.audit.service import to_jsonable
from app.modules.invoices.providers import get_assistant
from app.ports.extractor import ExtractorUnavailable

router = APIRouter(prefix="/assistant", tags=["assistant"])


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
