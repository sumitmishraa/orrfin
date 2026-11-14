"""HTTP routes for supplier onboarding: `/suppliers` for employees, `/portal` for suppliers (§9 v3.0).

The two routers use different dependencies on purpose. `/suppliers` needs an employee session
(`CurrentUser`). `/portal` needs a supplier session (`CurrentContact`, its own cookie) and never
reads the employee cookie, so neither kind of session opens the other's routes.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import throttle
from app.auth.dependencies import CurrentUser, DbSession
from app.config import get_settings
from app.errors import NotFound
from app.models import SupplierDocument, SupplierUser
from app.modules.audit.service import to_jsonable
from app.modules.invoices.providers import get_file_store
from app.modules.suppliers import portal, service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
portal_router = APIRouter(prefix="/portal", tags=["supplier portal"])


# --- Employees -------------------------------------------------------------------------------------

class InviteIn(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    category: str = Field(max_length=10)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)


class DecisionIn(BaseModel):
    decision: str = Field(max_length=10)
    reason: str | None = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("")
def list_suppliers(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable([service.summary(s) for s in service.list_suppliers(db, user)]))


@router.post("/invites", status_code=201)
def invite(body: InviteIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    supplier, token = service.invite(db, user, **body.model_dump())
    db.commit()
    # The link is shown once to the inviter (and "emailed" to the console locally); only its hash is stored.
    link = f"{get_settings().public_web_url.rstrip('/')}/portal/accept?token={token}"
    return JSONResponse(status_code=201, content=to_jsonable({**service.summary(supplier), "invite_link": link}),
                        headers={"Cache-Control": "no-store"})


@router.get("/{supplier_id}")
def get_supplier(supplier_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.detail(db, user, service.load_supplier(db, user, supplier_id))))


@router.post("/{supplier_id}/decision")
def decide(supplier_id: uuid.UUID, body: DecisionIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    supplier = service.decide(db, user, supplier_id, decision=body.decision, reason=body.reason)
    db.commit()
    return JSONResponse(to_jsonable(service.detail(db, user, supplier)))


@router.post("/{supplier_id}/handover")
def hand_over(supplier_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    supplier = service.hand_over(db, user, supplier_id)
    db.commit()
    return JSONResponse(to_jsonable(service.detail(db, user, supplier)))


@router.post("/{supplier_id}/clear-hold")
def clear_hold(supplier_id: uuid.UUID, body: ReasonIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    supplier = service.clear_hold(db, user, supplier_id, body.reason)
    db.commit()
    return JSONResponse(to_jsonable(service.detail(db, user, supplier)))


@router.get("/{supplier_id}/documents/{document_id}")
def download_document(supplier_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    supplier = service.load_supplier(db, user, supplier_id)
    document = db.get(SupplierDocument, document_id)
    if document is None or document.supplier_id != supplier.id:
        raise NotFound("Document not found.")
    # Served as a download with its checked type, so a browser never runs an uploaded file as a page.
    return Response(get_file_store().get(document.s3_key), media_type=document.content_type,
                    headers={"Content-Disposition": f'attachment; filename="supplier-document-{document.id}"',
                             "X-Content-Type-Options": "nosniff"})


# --- Supplier portal -------------------------------------------------------------------------------

def current_contact(request: Request, db: DbSession) -> SupplierUser:
    contact = portal.contact_for_token(db, request.cookies.get(portal.COOKIE_NAME))
    if contact is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to the supplier portal.")
    return contact


CurrentContact = Annotated[SupplierUser, Depends(current_contact)]


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PortalLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class ProfileIn(BaseModel):
    tax_id: str = Field(max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    answers: dict[str, str] = Field(default_factory=dict, max_length=20)


class BankIn(BaseModel):
    account_name: str = Field(min_length=1, max_length=200)
    account_number: str = Field(min_length=5, max_length=40)
    ifsc: str | None = Field(default=None, max_length=11)


def _throttle_key(email: str) -> str:
    # A different key space from employee logins: locking a supplier email never locks an employee.
    return f"supplier:{email.strip().lower()}"


@portal_router.post("/invites/accept", status_code=204)
def accept_invite(body: AcceptIn, db: DbSession) -> None:
    portal.accept_invite(db, body.token, body.password)
    db.commit()


@portal_router.post("/login")
def portal_login(body: PortalLoginIn, request: Request, response: Response, db: DbSession) -> dict[str, str]:
    key = _throttle_key(body.email)
    wait_seconds = throttle.seconds_locked(db, key)
    if wait_seconds:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many wrong passwords. Try again in {wait_seconds // 60 + 1} minutes.",
                            headers={"Retry-After": str(wait_seconds)})
    contact = portal.authenticate(db, body.email, body.password)
    if contact is None:
        throttle.record_failure(db, key)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    throttle.clear(db, key)
    previous = request.cookies.get(portal.COOKIE_NAME)
    if previous:
        portal.end_session(db, previous)  # a token planted before login is useless afterwards
    token = portal.start_session(db, contact)
    db.commit()
    settings = get_settings()
    response.set_cookie(portal.COOKIE_NAME, token, max_age=settings.session_hours * 3600, httponly=True,
                        samesite="lax", secure=settings.session_cookie_secure, path="/")
    return {"full_name": contact.full_name}


@portal_router.post("/logout", status_code=204)
def portal_logout(request: Request, response: Response, db: DbSession) -> None:
    token = request.cookies.get(portal.COOKIE_NAME)
    if token:
        portal.end_session(db, token)
        db.commit()
    response.delete_cookie(portal.COOKIE_NAME, path="/")


@portal_router.get("/me")
def portal_me(contact: CurrentContact, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(portal.view(db, contact)))


@portal_router.put("/profile")
def portal_profile(body: ProfileIn, contact: CurrentContact, db: DbSession) -> JSONResponse:
    portal.update_profile(db, contact, tax_id=body.tax_id, pan=body.pan, answers=body.answers)
    db.commit()
    return JSONResponse(to_jsonable(portal.view(db, contact)))


@portal_router.put("/bank")
def portal_bank(body: BankIn, contact: CurrentContact, db: DbSession) -> JSONResponse:
    portal.set_bank(db, contact, account_name=body.account_name, account_number=body.account_number, ifsc=body.ifsc)
    db.commit()
    return JSONResponse(to_jsonable(portal.view(db, contact)))


@portal_router.post("/documents", status_code=201)
def portal_document(contact: CurrentContact, db: DbSession, kind: Annotated[str, Form(max_length=20)],
                    file: Annotated[UploadFile, File()],
                    expires_on: Annotated[date | None, Form()] = None) -> JSONResponse:
    data = file.file.read(get_settings().max_upload_bytes + 1)
    portal.add_document(db, contact, kind=kind, filename=file.filename or "", content_type=file.content_type or "",
                        data=data, expires_on=expires_on)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(portal.view(db, contact)))


@portal_router.post("/submit")
def portal_submit(contact: CurrentContact, db: DbSession) -> JSONResponse:
    portal.submit(db, contact)
    db.commit()
    return JSONResponse(to_jsonable(portal.view(db, contact)))
