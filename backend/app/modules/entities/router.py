"""HTTP routes for legal entities and exchange rates (BUILD_PLAN §5, §9 v3.0).

Anyone signed in may read the entity list (the entity switcher needs it). Only an admin changes
an entity; only finance or an admin enters a rate. The service repeats those checks, so a route
added later cannot skip them.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession, require_roles
from app.modules.audit.service import to_jsonable
from app.modules.entities import service

router = APIRouter(prefix="/entities", tags=["entities"])
admin_only = [Depends(require_roles(*service.EDITOR_ROLES))]


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    base_currency: str = Field(min_length=3, max_length=3)
    tax_regime: str = Field(max_length=10)
    tax_id: str = Field(max_length=15)
    state_code: str | None = Field(default=None, max_length=2)
    erp_connection_id: uuid.UUID | None = None
    active: bool = True


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=500)


class RateIn(BaseModel):
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    # Text, not a JSON number: a rate must never pass through a float on its way in.
    rate: str = Field(pattern=r"^\d{1,10}(\.\d{1,8})?$")
    as_of: date


@router.get("")
def list_entities(user: CurrentUser, db: DbSession) -> JSONResponse:
    service.ensure_default(db, user.org_id)
    db.commit()
    return JSONResponse(to_jsonable([service.as_dict(e) for e in service.list_entities(db, user.org_id)]))


@router.post("", status_code=201, dependencies=admin_only)
def create_entity(body: EntityIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    entity = service.create_entity(db, user, body.model_dump())
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.as_dict(entity)))


@router.get("/fx-rates")
def list_rates(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(service.list_rates(db, user.org_id)))


@router.post("/fx-rates", status_code=201, dependencies=[Depends(require_roles(*service.FX_ROLES))])
def add_rate(body: RateIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    rate = service.add_rate(db, user, base=body.base_currency, quote=body.quote_currency,
                            rate=Decimal(body.rate), as_of=body.as_of)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable(service.rate_as_dict(rate, user.full_name)))


@router.put("/{entity_id}", dependencies=admin_only)
def update_entity(entity_id: uuid.UUID, body: EntityIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    entity = service.update_entity(db, user, entity_id, body.model_dump())
    db.commit()
    return JSONResponse(to_jsonable(service.as_dict(entity)))


@router.post("/{entity_id}/make-default", dependencies=admin_only)
def make_default(entity_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    entity = service.make_default(db, user, entity_id)
    db.commit()
    return JSONResponse(to_jsonable(service.as_dict(entity)))


@router.get("/{entity_id}/members", dependencies=admin_only)
def get_members(entity_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    entity = service.load_entity(db, user.org_id, entity_id)
    return JSONResponse(to_jsonable({"user_ids": service.members_of(db, entity)}))


@router.put("/{entity_id}/members", dependencies=admin_only)
def set_members(entity_id: uuid.UUID, body: MembersIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    members = service.set_members(db, user, entity_id, body.user_ids)
    db.commit()
    return JSONResponse(to_jsonable({"user_ids": members}))
