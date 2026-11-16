"""Team members, power seats and invitations through the API (BUILD_PLAN Step 41, ADR 0011, §9).

What must hold: only an admin manages the team; an invitation works once, is stored only as a hash
and expires; power seats are counted (requesters are free); nobody changes their own role or limit;
deactivating signs a person out at once; one org never sees or touches another org's team.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.models import AuditEvent, Notification, Org, TeamInvite, User
from tests.conftest import TEST_PASSWORD, login

NEW_PASSWORD = "team-member-pass-2026"


def _email(tag: str = "new") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@team.orrfin.local"


def _invite(client, admin, emails: list[str], role: str = "approver", **extra):
    login(client, admin)
    return client.post("/team/invites", json={"emails": emails, "role": role, **extra})


def _token(result: dict) -> str:
    return result["invite_link"].split("token=")[1]


def _accept(client, token: str, name: str = "Meera Iyer"):
    client.cookies.clear()
    return client.post("/auth/accept-invite", json={"token": token, "full_name": name, "password": NEW_PASSWORD})


def test_admin_invites_and_the_person_joins_with_the_chosen_role(client, db, factory):
    org = factory.org("Acme India")
    admin = factory.user(org, "admin", name="Anita Shah")
    first, second = _email(), _email()
    response = _invite(client, admin, [first, second, first.upper()], role="approver", approval_limit="250000",
                       department="Operations")
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["invited", "invited"]  # the duplicate was folded in

    token = _token(results[0])
    looked_up = client.get(f"/team/invites/lookup/{token}")
    assert looked_up.status_code == 200
    assert looked_up.json()["org_name"] == "Acme India" and looked_up.json()["invited_by_name"] == "Anita Shah"

    joined = _accept(client, token)
    assert joined.status_code == 200, joined.text
    assert joined.json()["role"] == "approver" and joined.json()["org_name"] == "Acme India"
    me = client.get("/auth/me").json()
    assert me["email"] == first and me["department"] == "Operations" and me["approval_limit"] in ("250000.00", 250000)

    # The same link never works twice.
    assert _accept(client, token).status_code == 422
    db.expire_all()
    member = db.scalar(select(User).where(User.email == first))
    assert member.invited_by_id == admin.id
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.org_id == org.id)).all())
    assert {"member_invited", "member_joined"} <= actions
    assert db.scalar(select(Notification).where(Notification.user_id == admin.id, Notification.kind == "team"))


def test_only_the_tokens_hash_is_stored(client, db, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    result = _invite(client, admin, [_email()]).json()["results"][0]
    token = _token(result)
    row = db.get(TeamInvite, uuid.UUID(str(result["invite_id"])))
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row.token_hash


def test_people_who_are_not_admins_cannot_manage_the_team(client, factory):
    org = factory.org()
    for role in ("requester", "buyer", "approver", "finance"):
        user = factory.user(org, role)
        login(client, user)
        assert client.get("/team/members").status_code == 403
        assert client.get("/team/plan").status_code == 403
        assert client.post("/team/invites", json={"emails": [_email()], "role": "requester"}).status_code == 403


def test_power_seats_are_counted_and_requesters_are_free(client, db, factory):
    org = factory.org()
    db.get(Org, org.id).power_seat_limit = 2
    db.commit()
    admin = factory.user(org, "admin")  # uses 1 of 2 seats

    over = _invite(client, admin, [_email(), _email()], role="approver")
    assert over.status_code == 409 and "power seat" in over.json()["detail"]

    assert _invite(client, admin, [_email()], role="buyer").status_code == 201  # the last seat, held by the invite
    assert _invite(client, admin, [_email()], role="finance").status_code == 409
    requesters = _invite(client, admin, [_email() for _ in range(5)], role="requester")
    assert requesters.status_code == 201
    plan = requesters.json()["plan"]
    assert plan["seats_used"] == 2 and plan["seat_limit"] == 2 and plan["pending_invites"] == 6

    # Promoting a requester to a power role needs a seat too.
    requester = factory.user(org, "requester")
    assert client.patch(f"/team/members/{requester.id}", json={"role": "approver"}).status_code == 409


def test_revoked_expired_and_resent_links(client, db, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    revoked = _invite(client, admin, [_email()]).json()["results"][0]
    assert client.delete(f"/team/invites/{revoked['invite_id']}").status_code == 204
    assert client.get(f"/team/invites/lookup/{_token(revoked)}").status_code == 422

    expiring = _invite(client, admin, [_email()]).json()["results"][0]
    row = db.get(TeamInvite, uuid.UUID(str(expiring["invite_id"])))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert _accept(client, _token(expiring)).status_code == 422

    login(client, admin)
    fresh = client.post(f"/team/invites/{expiring['invite_id']}/resend")
    assert fresh.status_code == 200 and fresh.json()["status"] == "pending"
    assert _accept(client, _token(expiring)).status_code == 422  # the old link stays dead
    assert _accept(client, _token(fresh.json())).status_code == 200


def test_an_existing_account_or_pending_invite_is_not_invited_again(client, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    someone = factory.user(factory.org("Other Org"), "requester")
    pending = _email()
    assert _invite(client, admin, [pending]).status_code == 201
    results = _invite(client, admin, [someone.email, pending, "not-an-email"]).json()["results"]
    assert {r["email"]: r["status"] for r in results} == {
        someone.email: "exists", pending: "already_invited", "not-an-email": "invalid"}


def test_nobody_changes_their_own_role_or_limit_or_deactivates_themselves(client, factory):
    org = factory.org()
    admin = factory.user(org, "admin", limit="1000")
    login(client, admin)
    assert client.patch(f"/team/members/{admin.id}", json={"role": "finance"}).status_code == 403
    assert client.patch(f"/team/members/{admin.id}", json={"approval_limit": "999999"}).status_code == 403
    assert client.post(f"/team/members/{admin.id}/deactivate").status_code == 403
    # Their own department is fine to change.
    assert client.patch(f"/team/members/{admin.id}", json={"department": "Finance"}).status_code == 200


def test_admin_changes_a_member_and_the_change_is_audited(client, db, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    manager = factory.user(org, "approver")
    buyer = factory.user(org, "buyer")
    login(client, admin)
    changed = client.patch(f"/team/members/{buyer.id}",
                           json={"role": "approver", "approval_limit": "50000", "manager_id": str(manager.id)})
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "approver" and changed.json()["manager_name"] == manager.full_name
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == buyer.id, AuditEvent.action == "member_updated"))
    assert event.actor_id == admin.id and set(event.payload["changes"]) == {"role", "approval_limit", "manager_id"}
    assert client.patch(f"/team/members/{buyer.id}", json={"manager_id": str(buyer.id)}).status_code == 422


def test_deactivating_signs_the_person_out_at_once_and_reactivating_restores_access(client, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    approver = factory.user(org, "approver")
    cookie = get_settings().session_cookie_name
    login(client, approver)
    approver_token = client.cookies.get(cookie)

    login(client, admin)
    gone = client.post(f"/team/members/{approver.id}/deactivate")
    assert gone.status_code == 200 and gone.json()["status"] == "deactivated"
    assert "open_work" in gone.json()

    client.cookies.clear()
    client.cookies.set(cookie, approver_token)
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"email": approver.email, "password": TEST_PASSWORD}).status_code == 401

    login(client, admin)
    assert client.post(f"/team/members/{approver.id}/reactivate").json()["status"] == "active"
    login(client, approver)


def test_one_org_never_sees_or_touches_another_orgs_team(client, factory):
    org_a, org_b = factory.org("A"), factory.org("B")
    admin_a, admin_b = factory.user(org_a, "admin"), factory.user(org_b, "admin")
    member_a = factory.user(org_a, "buyer")
    invite_a = _invite(client, admin_a, [_email()]).json()["results"][0]

    login(client, admin_b)
    emails = {m["email"] for m in client.get("/team/members").json()}
    assert member_a.email not in emails and admin_a.email not in emails
    assert client.get("/team/invites").json() == []
    assert client.get(f"/team/members/{member_a.id}").status_code == 404
    assert client.patch(f"/team/members/{member_a.id}", json={"department": "x"}).status_code == 404
    assert client.post(f"/team/members/{member_a.id}/deactivate").status_code == 404
    assert client.delete(f"/team/invites/{invite_a['invite_id']}").status_code == 404
    assert client.post(f"/team/invites/{invite_a['invite_id']}/resend").status_code == 404


def test_members_list_shows_seat_use_and_last_seen(client, factory):
    org = factory.org()
    admin = factory.user(org, "admin")
    factory.user(org, "requester")
    login(client, admin)
    members = {m["role"]: m for m in client.get("/team/members").json()}
    assert members["admin"]["uses_seat"] is True and members["requester"]["uses_seat"] is False
    assert members["admin"]["last_seen_at"] is not None
