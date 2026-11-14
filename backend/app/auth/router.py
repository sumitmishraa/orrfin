"""Login, logout and "who am I" endpoints (BUILD_PLAN Â§3 Auth, Â§9)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import throttle
from app.auth.dependencies import CurrentUser, DbSession
from app.auth.service import authenticate, end_session, start_session
from app.auth import totp
from app.config import get_settings
from app.modules.audit.service import record_event
from app.security.secrets import decrypt_credentials, encrypt_credentials

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str
    code: str | None = None  # v3.0: the 6-digit code, for people who switched on two-step sign-in


class Me(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    role: str
    approval_limit: Decimal
    mfa_enabled: bool = False


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
    if user.mfa_enabled_at is not None:
        if not body.code:
            # Not a wrong guess, so not counted: the page now asks for the code.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Enter the 6-digit code from your authenticator app.",
                                headers={"X-Orrfin-MFA": "required"})
        step = totp.verify(decrypt_credentials(user.mfa_secret_encrypted)["secret"], body.code,
                           last_step=user.mfa_last_step)
        if step is None:
            throttle.record_failure(db, body.email)
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That code is not right or was already used.",
                                headers={"X-Orrfin-MFA": "required"})
        user.mfa_last_step = step
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


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


def _audit_mfa(db, user, action: str) -> None:
    record_event(db, org_id=user.org_id, entity_type="user", entity_id=user.id, actor_id=user.id, action=action, payload={})


@router.post("/mfa/setup")
def mfa_setup(user: CurrentUser, db: DbSession) -> dict[str, str]:
    """Start two-step sign-in: a new secret for the authenticator app. Not active until a code proves it works."""
    if user.mfa_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step sign-in is already on. Switch it off first to start again.")
    secret = totp.new_secret()
    user.mfa_secret_encrypted, user.mfa_last_step = encrypt_credentials({"secret": secret}), None
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, user.email)}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, user: CurrentUser, db: DbSession) -> Me:
    from datetime import UTC, datetime

    if user.mfa_secret_encrypted is None or user.mfa_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start the setup first.")
    step = totp.verify(decrypt_credentials(user.mfa_secret_encrypted)["secret"], body.code, last_step=None)
    if step is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That code is not right. Check the time on your phone.")
    user.mfa_enabled_at, user.mfa_last_step = datetime.now(UTC), step
    _audit_mfa(db, user, "mfa_enabled")
    db.commit()
    return Me.model_validate(user, from_attributes=True)


@router.post("/mfa/disable")
def mfa_disable(body: CodeIn, user: CurrentUser, db: DbSession) -> Me:
    """Switching it off needs a current code too, so a stolen session alone cannot remove the second step."""
    if user.mfa_enabled_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step sign-in is not on.")
    if totp.verify(decrypt_credentials(user.mfa_secret_encrypted)["secret"], body.code, last_step=user.mfa_last_step) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That code is not right or was already used.")
    user.mfa_secret_encrypted = user.mfa_enabled_at = user.mfa_last_step = None
    _audit_mfa(db, user, "mfa_disabled")
    db.commit()
    return Me.model_validate(user, from_attributes=True)
