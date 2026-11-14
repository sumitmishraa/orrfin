"""HTTP routes for the AI layer: superagent chat, proposals, the workflow-builder agent (BUILD_PLAN change 47)."""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.errors import Forbidden
from app.models import AgentRun
from app.modules.agents import proposals, superagents, workflow_builder
from app.modules.assistant import service as assistant_service
from app.modules.audit.service import to_jsonable
from app.modules.invoices.providers import get_assistant, get_drafter
from app.ports.extractor import ExtractorUnavailable

router = APIRouter(prefix="/agents", tags=["agents"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=8)


class DescribeIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


def log_run(db, user, agent: str, channel: str, tools_used: list[str], proposal_ids: list[str], outcome: str) -> None:
    db.add(AgentRun(org_id=user.org_id, user_id=user.id, agent=agent, channel=channel, tools_used=tools_used,
                    proposal_ids=proposal_ids, outcome=outcome))


@router.get("")
def list_agents(user: CurrentUser) -> dict:
    return {name: {"title": s["title"], "summary": s["summary"]} for name, s in superagents.SUPERAGENTS.items()}


@router.post("/{agent}/ask")
def ask(agent: str, body: AskIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    tools = superagents.tools_for(db, user, agent)
    try:
        model = get_assistant()
    except ExtractorUnavailable:
        model = None
    reply = assistant_service.ask(db, user, body.question, body.history, None, model, tools=tools)
    cards = reply.get("proposals", [])
    log_run(db, user, agent, "chat", reply.get("tools_used", []), [str(c["id"]) for c in cards],
            "answered" if reply.get("available") else "unavailable")
    db.commit()
    return JSONResponse(to_jsonable(reply))


@router.post("/proposals/{proposal_id}/submit")
def submit(proposal_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    result = proposals.submit(db, user, proposal_id)
    db.commit()
    return JSONResponse(to_jsonable(result))


@router.post("/workflow-draft")
def workflow_draft(body: DescribeIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    """Words → a checked draft definition. Saves nothing; the builder page loads it for the admin to save."""
    if user.role != "admin":
        raise Forbidden("Only an admin can draft a workflow.")
    try:
        drafter = get_drafter()
    except ExtractorUnavailable:
        drafter = None
    result = workflow_builder.draft(db, user.org_id, body.text, drafter)
    log_run(db, user, "workflow", "chat", ["propose_workflow"], [], "drafted" if not result["problems"] else "problems")
    db.commit()
    return JSONResponse(to_jsonable(result))
