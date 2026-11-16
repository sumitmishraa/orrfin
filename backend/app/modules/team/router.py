"""HTTP routes for team members, seats and invitations (BUILD_PLAN Step 41, ADR 0011, §9).

`/team/*` needs an admin session, except the invitation lookup. `/auth/accept-invite` is public: the
single-use link is the proof. Invitation links appear only in the response that creates them.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import DbSession, require_roles
from app.auth.router import Me, me_for, set_session_cookie
from app.auth.service import end_session, start_session
from app.config import get_settings
from app.models import User
from app.modules.audit.service import to_jsonable
from app.modules.team import service

router = APIRouter(prefix="/team", tags=["team"])
accept_router = APIRouter(prefix="/auth", tags=["auth"])

Admin = Annotated[User, Depends(require_roles("admin"))]
NO_STORE = {"Cache-Control": "no-store"}


class InviteIn(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=service.MAX_BATCH)
    role: str = Field(max_length=20)
    approval_limit: Decimal = Field(default=Decimal("0"), ge=0)
    manager_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=80)


class MemberPatch(BaseModel):
    role: str | None = Field(default=None, max_length=20)
    approval_limit: Decimal | None = Field(default=None, ge=0)
    manager_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=80)


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.get("/plan")
def get_plan(admin: Admin, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.plan(db, admin.org_id)))


@router.get("/members")
def list_members(admin: Admin, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_members(db, admin)))


@router.get("/members/{user_id}")
def get_member(user_id: uuid.UUID, admin: Admin, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.member_detail(db, admin, user_id)))


@router.patch("/members/{user_id}")
def update_member(user_id: uuid.UUID, body: MemberPatch, admin: Admin, db: DbSession) -> JSONResponse:
    # Only the fields the admin actually sent change; "manager_id": null clears the manager.
    detail = service.update_member(db, admin, user_id, body.model_dump(exclude_unset=True))
    db.commit()
    return JSONResponse(to_jsonable(detail))


@router.post("/members/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, admin: Admin, db: DbSession) -> JSONResponse:
    detail = service.deactivate(db, admin, user_id)
    db.commit()
    return JSONResponse(to_jsonable(detail))


@router.post("/members/{user_id}/reactivate")
def reactivate(user_id: uuid.UUID, admin: Admin, db: DbSession) -> JSONResponse:
    detail = service.reactivate(db, admin, user_id)
    db.commit()
    return JSONResponse(to_jsonable(detail))


@router.get("/invites")
def list_invites(admin: Admin, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_invites(db, admin)))


@router.post("/invites", status_code=201)
def invite(body: InviteIn, admin: Admin, db: DbSession) -> JSONResponse:
    results = service.invite_many(db, admin, **body.model_dump())
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable({"results": results, "plan": service.plan(db, admin.org_id)}),
                        headers=NO_STORE)


@router.post("/invites/{invite_id}/resend")
def resend(invite_id: uuid.UUID, admin: Admin, db: DbSession) -> JSONResponse:
    row = service.resend(db, admin, invite_id)
    db.commit()
    return JSONResponse(to_jsonable(row), headers=NO_STORE)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke(invite_id: uuid.UUID, admin: Admin, db: DbSession) -> Response:
    service.revoke(db, admin, invite_id)
    db.commit()
    return Response(status_code=204)


@router.get("/invites/lookup/{token}")
def lookup(token: str, db: DbSession) -> JSONResponse:
    """Public: what the join page shows before the person sets a password."""
    return JSONResponse(to_jsonable(service.lookup(db, token)), headers=NO_STORE)


@accept_router.post("/accept-invite", response_model=Me)
def accept_invite(body: AcceptIn, request: Request, response: Response, db: DbSession) -> Me:
    member = service.accept(db, body.token, full_name=body.full_name, password=body.password)
    previous_token = request.cookies.get(get_settings().session_cookie_name)
    if previous_token:
        end_session(db, previous_token)  # whoever was signed in on this browser is signed out
    token = start_session(db, member)
    db.commit()
    set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return me_for(db, member)
