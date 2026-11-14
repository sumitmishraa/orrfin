"""API keys, signed webhooks and notifications (BUILD_PLAN v3.0 §5, §9, §11 M9).

What must hold: a key is shown once, stored as a hash, and dies when revoked, expired or its
owner is switched off; a webhook goes only to a public https address, is signed, and is never
followed through a redirect; a secret never comes back out; nobody reads another person's
notifications or another org's keys and webhooks.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import job_handlers  # noqa: F401  (registers webhook_deliver)
from app.jobs import drain
from app.models import ApiKey, Job, Notification, WebhookDelivery
from app.modules.integrations import api_keys, webhooks
from app.modules.notifications.service import notify
from tests.conftest import login
from tests.integration.test_procurement import (  # noqa: F401  (world is a fixture)
    _complete_and_send,
    _decide,
    _new_request,
    world,
)


# --- API keys --------------------------------------------------------------------------------------

def test_a_key_is_shown_once_and_only_its_hash_is_stored(client, db, world):
    login(client, world.buyer)
    created = client.post("/integrations/api-keys", json={"name": "Reporting script", "days": 30})
    assert created.status_code == 201, created.text
    raw_key = created.json()["key"]
    assert raw_key.startswith("orf_") and created.headers["cache-control"] == "no-store"

    listed = client.get("/integrations/api-keys").json()
    assert len(listed) == 1 and "key" not in listed[0] and "key_hash" not in listed[0]
    stored = db.get(ApiKey, uuid.UUID(created.json()["id"]))
    assert raw_key not in (stored.key_hash, stored.prefix) and len(stored.key_hash) == 64
    assert api_keys.user_for_key(db, raw_key).id == world.buyer.id
    assert api_keys.user_for_key(db, raw_key + "x") is None
    assert api_keys.user_for_key(db, "orf_guess") is None and api_keys.user_for_key(db, None) is None


def test_a_key_stops_working_when_revoked_expired_or_its_owner_is_switched_off(client, db, world):
    login(client, world.buyer)
    keys = [client.post("/integrations/api-keys", json={"name": f"k{i}"}).json() for i in range(3)]
    assert client.delete(f"/integrations/api-keys/{keys[0]['id']}").json()["revoked"] is True
    assert api_keys.user_for_key(db, keys[0]["key"]) is None

    expired = db.get(ApiKey, uuid.UUID(keys[1]["id"]))
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert api_keys.user_for_key(db, keys[1]["key"]) is None

    assert api_keys.user_for_key(db, keys[2]["key"]) is not None
    world.buyer.active = False
    db.commit()
    assert api_keys.user_for_key(db, keys[2]["key"]) is None


def test_key_limits_and_who_may_see_or_revoke_a_key(client, factory, world):
    login(client, world.buyer)
    for bad in ({"name": "", "days": 30}, {"name": "x", "days": 0}, {"name": "x", "days": 366}):
        assert client.post("/integrations/api-keys", json=bad).status_code == 422
    mine = client.post("/integrations/api-keys", json={"name": "mine"}).json()

    login(client, world.finance)                       # a colleague neither sees nor revokes it
    assert client.get("/integrations/api-keys").json() == []
    assert client.delete(f"/integrations/api-keys/{mine['id']}").status_code == 404
    other_admin = factory.user(factory.org("Other org"), "admin")
    login(client, other_admin)                         # nor does another org's admin
    assert client.get("/integrations/api-keys").json() == []
    assert client.delete(f"/integrations/api-keys/{mine['id']}").status_code == 404
    login(client, world.admin)                         # this org's admin can revoke a leaked key
    assert [k["id"] for k in client.get("/integrations/api-keys").json()] == [mine["id"]]
    assert client.delete(f"/integrations/api-keys/{mine['id']}").status_code == 200

    login(client, world.buyer)
    for i in range(api_keys.MAX_ACTIVE_KEYS):
        assert client.post("/integrations/api-keys", json={"name": f"k{i}"}).status_code == 201
    assert client.post("/integrations/api-keys", json={"name": "one too many"}).status_code == 409


# --- Webhooks --------------------------------------------------------------------------------------

@pytest.fixture
def receiver(monkeypatch):
    """A fake receiving server. `calls` collects what Orrfin sent; `status` is what it answers."""
    state = {"calls": [], "status": 200}

    def handle(request: httpx.Request) -> httpx.Response:
        state["calls"].append(request)
        return httpx.Response(state["status"], headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(webhooks, "TRANSPORT", httpx.MockTransport(handle))
    return state


def _webhook(client, world, events=("request.approved",), url=None):
    """Register a webhook. Each test gets its own address, because the test database is shared within a run."""
    login(client, world.admin)
    url = url or f"https://hooks.example.com/{uuid.uuid4().hex}"
    return client.post("/integrations/webhooks", json={"url": url, "events": list(events)})


def _calls_to(receiver, endpoint: dict) -> list[httpx.Request]:
    return [c for c in receiver["calls"] if str(c.url) == endpoint["url"]]


def _deliveries(db, endpoint: dict) -> list[WebhookDelivery]:
    db.expire_all()
    return list(db.scalars(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == uuid.UUID(endpoint["id"]))))


def test_only_an_admin_manages_webhooks_and_the_secret_is_shown_once(client, factory, world):
    for user in (world.requester, world.buyer, world.finance):
        login(client, user)
        assert client.get("/integrations/webhooks").status_code == 403
        assert client.post("/integrations/webhooks", json={"url": "https://hooks.example.com/x",
                                                           "events": ["ping"]}).status_code == 403
    created = _webhook(client, world)
    assert created.status_code == 201, created.text
    assert created.json()["secret"].startswith("whsec_")
    listed = client.get("/integrations/webhooks").json()["endpoints"]
    assert len(listed) == 1 and "secret" not in listed[0] and "secret_encrypted" not in listed[0]

    login(client, factory.user(factory.org("Other org"), "admin"))
    endpoint_id = created.json()["id"]
    assert client.get("/integrations/webhooks").json()["endpoints"] == []
    assert client.get(f"/integrations/webhooks/{endpoint_id}/deliveries").status_code == 404
    assert client.post(f"/integrations/webhooks/{endpoint_id}/test").status_code == 404
    assert client.put(f"/integrations/webhooks/{endpoint_id}/active", json={"active": False}).status_code == 404


@pytest.mark.parametrize("url", [
    "http://hooks.example.com/x",              # not encrypted
    "https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://192.168.1.10/x",
    "https://169.254.169.254/latest/meta-data/",  # the cloud metadata address
    "https://[::1]/x", "https://user:pass@hooks.example.com/x", "ftp://hooks.example.com/x", "not a url",
])
def test_a_webhook_address_inside_the_network_is_refused(client, world, url):
    assert _webhook(client, world, url=url).status_code == 422
    assert _webhook(client, world, events=("made.up",)).status_code == 422


def test_an_approved_request_is_delivered_signed_and_the_requester_is_told(client, db, world, receiver):
    endpoint = _webhook(client, world).json()
    secret = endpoint["secret"]
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    assert _decide(client, world.manager, request["id"], 1).json()["status"] == "approved"
    drain(db)

    sent = _calls_to(receiver, endpoint)
    assert len(sent) == 1
    body = sent[0].content
    assert webhooks.verify_signature(secret, sent[0].headers["X-Orrfin-Signature"], body)
    assert not webhooks.verify_signature(secret, sent[0].headers["X-Orrfin-Signature"], body + b" ")   # altered
    assert not webhooks.verify_signature("whsec_wrong", sent[0].headers["X-Orrfin-Signature"], body)
    old = int(datetime.now(UTC).timestamp()) + 3600
    assert not webhooks.verify_signature(secret, sent[0].headers["X-Orrfin-Signature"], body, now=old)  # replayed late
    payload = json.loads(body)
    assert payload["event"] == "request.approved" and payload["data"]["amount"] == "40000.00"
    assert [d.status for d in _deliveries(db, endpoint)] == ["delivered"]

    login(client, world.requester)
    inbox = client.get("/notifications").json()
    assert inbox["unread"] == 1 and inbox["items"][0]["link"] == f"/requests/{request['id']}"
    assert client.post("/notifications/read-all").json() == {"marked_read": 1}
    assert client.get("/notifications").json()["unread"] == 0
    login(client, world.manager)
    assert client.get("/notifications").json()["items"] == []     # nobody else sees it


def test_a_redirect_is_not_followed_and_a_failing_receiver_is_retried_then_marked_failed(client, db, world, receiver):
    endpoint = _webhook(client, world, events=("ping",)).json()
    receiver["status"] = 302
    assert client.post(f"/integrations/webhooks/{endpoint['id']}/test").json() == {"queued": 1}
    drain(db)
    assert len(_calls_to(receiver, endpoint)) == 1
    assert all(c.url.host == "hooks.example.com" for c in receiver["calls"])   # the Location header was ignored
    (delivery,) = _deliveries(db, endpoint)
    assert (delivery.status, delivery.response_code, delivery.attempts) == ("pending", 302, 1)

    job = db.scalar(select(Job).where(Job.kind == "webhook_deliver",
                                      Job.payload["delivery_id"].astext == str(delivery.id)))
    job.attempts, job.run_after = job.max_attempts - 1, datetime.now(UTC)
    db.commit()
    drain(db)
    assert [d.status for d in _deliveries(db, endpoint)] == ["failed"]
    shown = client.get(f"/integrations/webhooks/{endpoint['id']}/deliveries").json()
    assert shown[0]["status"] == "failed" and "302" in shown[0]["last_error"]


def test_a_switched_off_webhook_gets_nothing(client, db, world, receiver):
    endpoint = _webhook(client, world).json()
    assert client.put(f"/integrations/webhooks/{endpoint['id']}/active", json={"active": False}).status_code == 200
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    _decide(client, world.manager, request["id"], 1)
    drain(db)
    assert _calls_to(receiver, endpoint) == [] and _deliveries(db, endpoint) == []


# --- Notifications ---------------------------------------------------------------------------------

def test_a_notification_never_links_outside_the_app_or_reaches_another_org(client, db, factory, world):
    outsider = factory.user(factory.org("Other org"), "requester")
    assert notify(db, org_id=world.org.id, user_id=outsider.id, kind="x", title="Not yours") is None
    for bad_link in ("https://evil.example/login", "//evil.example", "javascript:alert(1)"):
        row = notify(db, org_id=world.org.id, user_id=world.requester.id, kind="x", title="Hi", link=bad_link)
        assert row.link is None
    db.commit()
    login(client, world.buyer)
    someone_elses = db.scalar(select(Notification.id).where(Notification.user_id == world.requester.id))
    assert client.post(f"/notifications/{someone_elses}/read").json() == {"marked_read": 0}
