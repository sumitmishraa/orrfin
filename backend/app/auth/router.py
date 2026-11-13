"""Login, logout and "who am I" endpoints (BUILD_PLAN §3 Auth, §9)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth import throttle
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
def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> Me:
    wait_seconds = throttle.seconds_locked(db, body.email)
    if wait_seconds:
        # Checked before the password, so a locked email learns nothing from further guesses.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many wrong passwords. Try again in {wait_seconds // 60 + 1} minutes.",
            headers={"Retry-After": str(wait_seconds)},
        )
    user = authenticate(db, body.email, body.password)
    if user is None:
        throttle.record_failure(db, body.email)
        db.commit()
        # One message for both cases, so the form doesn't reveal which emails exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    throttle.clear(db, body.email)
    settings = get_settings()
    # A new login always gets a new token, and the one this browser held stops working. A token
    # planted in the browser before login (session fixation) is therefore useless afterwards.
    previous_token = request.cookies.get(settings.session_cookie_name)
    if previous_token:
        end_session(db, previous_token)
    token = start_session(db, user)
    db.commit()
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
