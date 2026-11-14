"""HTTP routes for API keys and webhooks (BUILD_PLAN v3.0 §5, §9).

A key or a webhook secret appears in exactly one response: the one that creates it.
"""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.integrations import api_keys, webhooks

router = APIRouter(prefix="/integrations", tags=["integrations"])


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    days: int = Field(default=90, ge=1, le=api_keys.MAX_DAYS)


class WebhookIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(min_length=1, max_length=len(webhooks.EVENTS))


class ActiveIn(BaseModel):
    active: bool


@router.get("/api-keys")
def list_keys(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable([api_keys.as_dict(k) for k in api_keys.list_keys(db, user)]))


@router.post("/api-keys", status_code=201)
def create_key(body: KeyIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    key, raw_key = api_keys.create_key(db, user, name=body.name, days=body.days)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable({**api_keys.as_dict(key), "key": raw_key}),
                        headers={"Cache-Control": "no-store"})


@router.delete("/api-keys/{key_id}")
def revoke_key(key_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    key = api_keys.revoke_key(db, user, key_id)
    db.commit()
    return JSONResponse(to_jsonable(api_keys.as_dict(key)))


@router.get("/webhooks")
def list_webhooks(user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable({"events": [e for e in webhooks.EVENTS if e != "ping"],
                                     "endpoints": [webhooks.as_dict(e) for e in webhooks.list_endpoints(db, user)]}))


@router.post("/webhooks", status_code=201)
def create_webhook(body: WebhookIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    endpoint, secret = webhooks.create_endpoint(db, user, url=body.url, events=body.events)
    db.commit()
    return JSONResponse(status_code=201, content=to_jsonable({**webhooks.as_dict(endpoint), "secret": secret}),
                        headers={"Cache-Control": "no-store"})


@router.put("/webhooks/{endpoint_id}/active")
def set_webhook_active(endpoint_id: uuid.UUID, body: ActiveIn, user: CurrentUser, db: DbSession) -> JSONResponse:
    endpoint = webhooks.set_active(db, user, endpoint_id, body.active)
    db.commit()
    return JSONResponse(to_jsonable(webhooks.as_dict(endpoint)))


@router.post("/webhooks/{endpoint_id}/test")
def test_webhook(endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, int]:
    endpoint = webhooks.load_endpoint(db, user, endpoint_id)
    queued = webhooks.emit(db, user.org_id, "ping", {"message": "Test from Orrfin"}, only=endpoint)
    db.commit()
    return {"queued": queued}


@router.get("/webhooks/{endpoint_id}/deliveries")
def list_deliveries(endpoint_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    return JSONResponse(to_jsonable(webhooks.deliveries(db, user, endpoint_id)))
