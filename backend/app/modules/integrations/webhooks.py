"""Signed outbound webhooks (BUILD_PLAN v3.0 §5 `webhook_endpoints`, `webhook_deliveries`; §9).

An admin registers an https address and picks events. When an event happens, Orrfin stores a
delivery row in the same transaction and a job posts it. What keeps this safe:
- the address must be public https; private, loopback and link-local addresses are refused when
  it is saved and again just before every send (an address can change where it points);
- redirects are never followed, the reply is never read back into Orrfin, and it has a timeout;
- each call carries `X-Orrfin-Signature: t=<unix time>,v1=<HMAC-SHA256 of "t.body">`, signed with
  a secret shown once and stored encrypted, so the receiver can prove who sent it and when;
- a payload holds ids, statuses and amounts only: never a credential, a bank detail or a document.
A webhook tells another system that something happened; nothing ever comes back in.
"""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.jobs import enqueue, handler
from app.models import Job, User, WebhookDelivery, WebhookEndpoint
from app.modules.audit.service import record_event, to_jsonable
from app.security.outbound import HostPolicy, UrlNotAllowed, check_base_url, redact
from app.security.secrets import decrypt_credentials, encrypt_credentials

EVENTS = ("invoice.matched", "invoice.exception", "request.approved", "request.rejected", "ping")
PUBLIC_HTTPS = HostPolicy(allow_any_public_https=True)
MAX_ENDPOINTS = 10
SIGNATURE_HEADER = "X-Orrfin-Signature"
TOLERANCE_SECONDS = 300
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# Tests swap in an httpx.MockTransport here; None means the real network.
TRANSPORT: httpx.BaseTransport | None = None


def sign(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(secret: str, header: str, body: bytes, *, now: int | None = None) -> bool:
    """What a receiver does: recompute the signature and refuse an old or altered message."""
    try:
        parts = dict(part.split("=", 1) for part in header.split(","))
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else int(time.time())) - timestamp) > TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), f"t={timestamp},v1={parts.get('v1', '')}")


def as_dict(endpoint: WebhookEndpoint) -> dict[str, Any]:
    """What the browser may see. Never the secret."""
    return {"id": endpoint.id, "url": endpoint.url, "events": endpoint.events, "active": endpoint.active,
            "created_at": endpoint.created_at}


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise Forbidden("Only an admin can manage webhooks.")


def _checked_url(url: str) -> str:
    try:
        return check_base_url(url, PUBLIC_HTTPS)
    except UrlNotAllowed as exc:
        raise Invalid(f"That address cannot be used for a webhook: {exc}") from exc


def create_endpoint(db: Session, user: User, *, url: str, events: list[str]) -> tuple[WebhookEndpoint, str]:
    """Register an address. Returns the row and its signing secret, which is shown once."""
    _require_admin(user)
    unknown = sorted(set(events) - set(EVENTS))
    if unknown or not events:
        raise Invalid(f"Choose at least one event from: {', '.join(EVENTS)}.")
    clean_url = _checked_url(url)
    count = len(list_endpoints(db, user))
    if count >= MAX_ENDPOINTS:
        raise Conflict(f"An org can have at most {MAX_ENDPOINTS} webhook addresses.")
    secret = "whsec_" + secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(id=uuid.uuid4(), org_id=user.org_id, url=clean_url, events=sorted(set(events)),
                               secret_encrypted=encrypt_credentials({"secret": secret}), created_by=user.id)
    db.add(endpoint)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="webhook_endpoint", entity_id=endpoint.id, actor_id=user.id,
                 action="created", payload={"url": clean_url, "events": endpoint.events})
    return endpoint, secret


def list_endpoints(db: Session, user: User) -> list[WebhookEndpoint]:
    _require_admin(user)
    return list(db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.org_id == user.org_id)
                           .order_by(WebhookEndpoint.created_at)))


def load_endpoint(db: Session, user: User, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    _require_admin(user)
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id,
                                                       WebhookEndpoint.org_id == user.org_id))
    if endpoint is None:
        raise NotFound("Webhook not found.")
    return endpoint


def set_active(db: Session, user: User, endpoint_id: uuid.UUID, active: bool) -> WebhookEndpoint:
    endpoint = load_endpoint(db, user, endpoint_id)
    if endpoint.active != active:
        endpoint.active = active
        record_event(db, org_id=user.org_id, entity_type="webhook_endpoint", entity_id=endpoint.id,
                     actor_id=user.id, action="switched_on" if active else "switched_off", payload={})
    return endpoint


def deliveries(db: Session, user: User, endpoint_id: uuid.UUID) -> list[dict[str, Any]]:
    endpoint = load_endpoint(db, user, endpoint_id)
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
                      .order_by(WebhookDelivery.created_at.desc()).limit(50))
    return [{"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts,
             "response_code": d.response_code, "last_error": d.last_error, "at": d.created_at} for d in rows]


def emit(db: Session, org_id: uuid.UUID, event: str, data: dict[str, Any], *,
         only: WebhookEndpoint | None = None) -> int:
    """Queue `event` for every address of this org that asked for it. Runs in the caller's transaction."""
    endpoints = [only] if only is not None else list(db.scalars(select(WebhookEndpoint).where(
        WebhookEndpoint.org_id == org_id, WebhookEndpoint.active)))
    queued = 0
    for endpoint in endpoints:
        if event not in endpoint.events and event != "ping":
            continue
        payload = to_jsonable({"event": event, "data": data})
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        delivery = WebhookDelivery(id=uuid.uuid4(), org_id=org_id, endpoint_id=endpoint.id, event=event,
                                   payload=payload, payload_sha256=hashlib.sha256(body).hexdigest())
        db.add(delivery)
        db.flush()
        enqueue(db, org_id=org_id, kind="webhook_deliver", payload={"delivery_id": str(delivery.id)})
        queued += 1
    return queued


def _gave_up(db: Session, job: Job, error: str) -> None:
    delivery = db.get(WebhookDelivery, uuid.UUID(job.payload["delivery_id"]))
    if delivery is not None and delivery.status == "pending":
        delivery.status = "failed"


@handler("webhook_deliver", on_give_up=_gave_up)
def deliver(db: Session, job: Job) -> dict[str, Any]:
    delivery = db.get(WebhookDelivery, uuid.UUID(job.payload["delivery_id"]), with_for_update=True)
    if delivery is None or delivery.status != "pending":
        return {"skipped": delivery.status if delivery else "missing"}
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    if not endpoint.active:
        delivery.status, delivery.last_error = "failed", "The webhook was switched off before this was sent."
        return {"skipped": "inactive"}
    secret = decrypt_credentials(endpoint.secret_encrypted)["secret"]
    body = json.dumps(delivery.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    delivery.attempts += 1
    code: int | None = None
    try:
        url = check_base_url(endpoint.url, PUBLIC_HTTPS)  # checked again: the name may now point somewhere private
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=TRANSPORT) as client:
            response = client.post(url, content=body, headers={
                "Content-Type": "application/json", "User-Agent": "Orrfin-Webhooks/1",
                SIGNATURE_HEADER: sign(secret, int(time.time()), body), "X-Orrfin-Delivery": str(delivery.id)})
        code = response.status_code
        problem = None if 200 <= code < 300 else f"The receiver answered {code}."
    except UrlNotAllowed as exc:
        problem = f"Address refused: {exc}"
    except httpx.HTTPError as exc:
        problem = f"Could not reach the receiver ({type(exc).__name__})."
    delivery.response_code = code
    if problem is None:
        delivery.status, delivery.last_error = "delivered", None
        return {"status": "delivered", "code": code}
    delivery.last_error = redact(problem, [secret])[:300]
    db.commit()  # keep the attempt on record; raising below makes the job retry with back-off
    raise RuntimeError(delivery.last_error)
