"""HTTP routes for simulated payments (BUILD_PLAN v2.4 change 31; ADR 0008; PROMPTS Step 25).

Finance and admins only (service.py enforces it). Each action commits once with its audit event.
Importing this module registers the dashboard's payments section.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.insights.service import SECTION_PROVIDERS
from app.modules.payments import service

router = APIRouter(tags=["payments"])


def _json(value) -> JSONResponse:
    return JSONResponse(to_jsonable(value))


class ProfileIn(BaseModel):
    pan: str | None = Field(default=None, max_length=10)
    tds_section: Literal["194C", "194J", "194Q"] | None = None
    payee_type: Literal["individual", "company", "other"] = "company"
    j_kind: Literal["professional", "technical"] = "professional"
    account_name: str = Field(min_length=1, max_length=140)
    bank_account: str = Field(min_length=9, max_length=24)
    ifsc: str | None = Field(default=None, min_length=11, max_length=11)
    swift_bic: str | None = Field(default=None, min_length=8, max_length=11)  # v3.0: with an IBAN in bank_account


class NewRunIn(BaseModel):
    currency: str = Field(default="INR", min_length=3, max_length=3)


class AddInvoiceIn(BaseModel):
    invoice_id: uuid.UUID


class ApproveIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


@router.get("/payment-profiles")
def profiles(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.profiles_view(db, user))


@router.put("/payment-profiles/{vendor_id}")
def save_profile(vendor_id: uuid.UUID, body: ProfileIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.save_profile(db, user, vendor_id, **body.model_dump())
    db.commit()
    return _json(service.profiles_view(db, user))


@router.post("/payment-profiles/{vendor_id}/verify")
def verify_profile(vendor_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    service.verify_profile(db, user, vendor_id)
    db.commit()
    return _json(service.profiles_view(db, user))


@router.get("/payments/eligible")
def eligible(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.eligible_invoices(db, user))


@router.get("/payment-runs")
def runs(user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.runs_view(db, user))


@router.post("/payment-runs", status_code=201)
def create_run(user: CurrentUser, db: DbSession, body: NewRunIn | None = None) -> JSONResponse:
    run = service.create_run(db, user, (body or NewRunIn()).currency)
    db.commit()
    return JSONResponse(to_jsonable(service.run_view(db, user, run)), status_code=201)


@router.get("/payment-runs/{run_id}")
def get_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _json(service.run_view(db, user, service._load_run(db, user, run_id)))


def _act(db, user, run) -> JSONResponse:
    db.commit()
    return _json(service.run_view(db, user, run))


@router.post("/payment-runs/{run_id}/invoices")
def add_invoice(run_id: uuid.UUID, body: AddInvoiceIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.add_invoice(db, user, run_id, body.invoice_id))


@router.delete("/payment-runs/{run_id}/lines/{line_id}")
def remove_line(run_id: uuid.UUID, line_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.remove_line(db, user, run_id, line_id))


@router.post("/payment-runs/{run_id}/submit")
def submit(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.submit_run(db, user, run_id))


@router.post("/payment-runs/{run_id}/approve")
def approve(run_id: uuid.UUID, body: ApproveIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.approve_run(db, user, run_id, body.reason))


@router.post("/payment-runs/{run_id}/cancel")
def cancel(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.cancel_run(db, user, run_id))


@router.post("/payment-runs/{run_id}/send")
def send(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return _act(db, user, service.send_to_bank(db, user, run_id))


@router.get("/payment-runs/{run_id}/bank-file")
def bank_file(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    name, text = service.download_bank_file(db, user, run_id)
    db.commit()  # the download itself is audited
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/payment-runs/{run_id}/bank-statement")
def bank_statement(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    name, data = service.bank_statement(db, user, run_id)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


SECTION_PROVIDERS["payments"] = service.payments_section


@router.get("/payment-runs/{run_id}/advice")
def payment_advice(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    name, pdf = service.payment_advice(db, user, run_id)
    db.commit()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
