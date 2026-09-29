"""FastAPI dependencies: the logged-in user and role checks (BUILD_PLAN §9).

Every business route depends on `current_user`; every query then filters on
`user.org_id`, which is how one org can never see another org's rows.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import user_for_token
from app.config import get_settings
from app.db import get_session
from app.models import User

DbSession = Annotated[Session, Depends(get_session)]


def current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(get_settings().session_cookie_name)
    user = user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: str) -> Callable[[User], User]:
    """Route guard: only the listed roles may call this endpoint."""
    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this.")
        return user
    return guard
