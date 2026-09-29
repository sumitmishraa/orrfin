"""Login, logout and "who am I" endpoints (BUILD_PLAN §3 Auth, §9)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser, DbSession
from app.auth.service import authenticate, end_session, start_session
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class Me(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    role: str
    approval_limit: Decimal


@router.post("/login", response_model=Me)
def login(body: LoginRequest, response: Response, db: DbSession) -> Me:
    user = authenticate(db, body.email, body.password)
    if user is None:
        # One message for both cases, so the form doesn't reveal which emails exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    token = start_session(db, user)
    db.commit()
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,  # page scripts can't read it, so an XSS bug can't steal the session
        samesite="lax",  # other sites can't make the browser send it on a POST
        secure=settings.session_cookie_secure,
        path="/",
    )
    return Me.model_validate(user, from_attributes=True)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        end_session(db, token)
        db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me", response_model=Me)
def me(user: CurrentUser) -> Me:
    return Me.model_validate(user, from_attributes=True)
