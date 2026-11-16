"""Team members, roles, seats and invitations (BUILD_PLAN Step 41, ADR 0011, §9).

The admin who buys Orrfin invites the rest of the team. Rules that hold here, on the server:
- only an admin manages the team (the router guards every route; services check again);
- requesters are free and unlimited; buyer, approver, finance and admin each use one power seat,
  and a pending invitation holds its seat until it is used, revoked or expires (simulated plan);
- an invitation link is single-use, only its SHA-256 is stored, and it expires in 7 days;
- nobody changes their own role or approval limit, and the last active admin can never be
  demoted or deactivated, so a workspace can never lock itself out;
- people are deactivated, never deleted: their audit trail and past approvals must stay readable,
  and deactivating ends every session they have at once.
Every change writes its audit event in the same transaction.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import get_settings
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import (
    ROLES,
    AuditEvent,
    ExceptionTask,
    Org,
    RequestApproval,
    TeamInvite,
    User,
    UserSession,
)
from app.modules.audit.service import record_event
from app.modules.notifications.service import notify

log = logging.getLogger("orrfin.email")

POWER_ROLES = ("buyer", "approver", "finance", "admin")
INVITE_DAYS = 7  # §9: invitation links expire in 7 days
MAX_BATCH = 25  # one invite dialog; a bigger roll-out belongs to SSO/SCIM, not pasted emails
MIN_PASSWORD = 12
ROLE_NAMES = {"requester": "Requester", "buyer": "Buyer", "approver": "Approver", "finance": "Finance",
              "admin": "Admin"}


def _now() -> datetime:
    return datetime.now(UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_link(token: str) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/join?token={token}"


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise Forbidden("Only an admin can manage the team.")


def _audit(db: Session, *, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, actor_id: uuid.UUID | None,
           action: str, payload: dict[str, Any] | None = None) -> None:
    record_event(db, org_id=org_id, entity_type=entity_type, entity_id=entity_id, actor_id=actor_id,
                 action=action, payload=payload or {})


# --- Seats ------------------------------------------------------------------------------------------

def _pending_invites(org_id: uuid.UUID):
    return select(TeamInvite).where(TeamInvite.org_id == org_id, TeamInvite.used_at.is_(None),
                                    TeamInvite.revoked_at.is_(None), TeamInvite.expires_at > _now())


def seats_used(db: Session, org_id: uuid.UUID) -> int:
    members = db.scalar(select(func.count()).select_from(User).where(
        User.org_id == org_id, User.active, User.role.in_(POWER_ROLES))) or 0
    invited = db.scalar(select(func.count()).select_from(
        _pending_invites(org_id).where(TeamInvite.role.in_(POWER_ROLES)).subquery())) or 0
    return members + invited


def plan(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    org = db.get(Org, org_id)
    requesters = db.scalar(select(func.count()).select_from(User).where(
        User.org_id == org_id, User.active, User.role == "requester")) or 0
    pending = db.scalar(select(func.count()).select_from(_pending_invites(org_id).subquery())) or 0
    return {"plan_name": org.plan_name, "seat_limit": org.power_seat_limit, "seats_used": seats_used(db, org_id),
            "requesters": requesters, "pending_invites": pending, "power_roles": list(POWER_ROLES)}


def _require_seats(db: Session, org_id: uuid.UUID, needed: int) -> None:
    if needed <= 0:
        return
    org = db.get(Org, org_id)
    free = org.power_seat_limit - seats_used(db, org_id)
    if needed > free:
        raise Conflict(
            f"Your {org.plan_name} plan has {max(free, 0)} power seat{'s' if free != 1 else ''} free and this needs "
            f"{needed}. Invite them as requesters (always free), free a seat, or raise the plan's seat limit.")


def _active_admins(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.org_id == org_id, User.active, User.role == "admin")) or 0


# --- Reading ----------------------------------------------------------------------------------------

def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _member(user: User, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
            "department": user.department, "approval_limit": user.approval_limit,
            "manager_id": user.manager_id, "manager_name": names.get(user.manager_id),
            "invited_by_name": names.get(user.invited_by_id), "status": "active" if user.active else "deactivated",
            "mfa_enabled": user.mfa_enabled, "uses_seat": user.role in POWER_ROLES,
            "last_seen_at": user.last_seen_at, "joined_at": user.created_at}


def list_members(db: Session, admin: User) -> list[dict[str, Any]]:
    _require_admin(admin)
    users = db.scalars(select(User).where(User.org_id == admin.org_id)
                       .order_by(User.active.desc(), func.lower(User.full_name))).all()
    names = _names(db, {u.manager_id for u in users} | {u.invited_by_id for u in users})
    return [_member(u, names) for u in users]


def _load_member(db: Session, admin: User, user_id: uuid.UUID, *, lock: bool = False) -> User:
    _require_admin(admin)
    query = select(User).where(User.id == user_id, User.org_id == admin.org_id)
    member = db.scalar(query.with_for_update() if lock else query)
    if member is None:
        raise NotFound("Team member not found.")
    return member


def open_work(db: Session, member: User) -> dict[str, int]:
    """What would be left waiting if this person left: their open questions and named approval steps."""
    questions = db.scalar(select(func.count()).select_from(ExceptionTask).where(
        ExceptionTask.org_id == member.org_id, ExceptionTask.assigned_to == member.id,
        ExceptionTask.status == "open")) or 0
    approvals = db.scalar(select(func.count()).select_from(RequestApproval).where(
        RequestApproval.org_id == member.org_id, RequestApproval.designated_approver_id == member.id,
        RequestApproval.decision.is_(None))) or 0
    return {"open_questions": questions, "named_approvals": approvals}


def member_detail(db: Session, admin: User, user_id: uuid.UUID) -> dict[str, Any]:
    member = _load_member(db, admin, user_id)
    names = _names(db, {member.manager_id, member.invited_by_id})
    events = db.scalars(select(AuditEvent).where(
        AuditEvent.org_id == admin.org_id,
        or_(AuditEvent.actor_id == member.id,
            (AuditEvent.entity_type == "user") & (AuditEvent.entity_id == member.id)))
        .order_by(AuditEvent.created_at.desc()).limit(25)).all()
    actor_names = _names(db, {e.actor_id for e in events})
    activity = [{"at": e.created_at, "entity_type": e.entity_type, "entity_id": e.entity_id, "action": e.action,
                 "actor_name": actor_names.get(e.actor_id)} for e in events]
    return {**_member(member, names), "open_work": open_work(db, member), "activity": activity}


def _invite_status(invite: TeamInvite) -> str:
    if invite.used_at is not None:
        return "accepted"
    if invite.revoked_at is not None:
        return "revoked"
    return "expired" if invite.expires_at <= _now() else "pending"


def _invite_dict(invite: TeamInvite, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": invite.id, "email": invite.email, "role": invite.role, "department": invite.department,
            "approval_limit": invite.approval_limit, "manager_name": names.get(invite.manager_id),
            "invited_by_name": names.get(invite.invited_by_id), "status": _invite_status(invite),
            "uses_seat": invite.role in POWER_ROLES, "sent_at": invite.updated_at, "expires_at": invite.expires_at}


def list_invites(db: Session, admin: User) -> list[dict[str, Any]]:
    """Invitations not yet accepted: pending ones first, then expired or revoked ones from the last 30 days."""
    _require_admin(admin)
    invites = db.scalars(select(TeamInvite).where(
        TeamInvite.org_id == admin.org_id, TeamInvite.used_at.is_(None),
        TeamInvite.updated_at > _now() - timedelta(days=30)).order_by(TeamInvite.updated_at.desc())).all()
    names = _names(db, {i.manager_id for i in invites} | {i.invited_by_id for i in invites})
    rows = [_invite_dict(i, names) for i in invites]
    return sorted(rows, key=lambda r: r["status"] != "pending")


# --- Inviting ---------------------------------------------------------------------------------------

def _clean_role(role: str) -> str:
    if role not in ROLES:
        raise Invalid("Choose one of the roles: requester, buyer, approver, finance or admin.")
    return role


def _clean_limit(value: Any) -> Decimal:
    try:
        limit = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise Invalid("The approval limit must be an amount, for example 50000.") from None
    if limit < 0 or limit >= Decimal("1e16"):
        raise Invalid("The approval limit must be zero or more.")
    return limit


def _clean_manager(db: Session, org_id: uuid.UUID, manager_id: uuid.UUID | None) -> uuid.UUID | None:
    if manager_id is None:
        return None
    manager = db.scalar(select(User).where(User.id == manager_id, User.org_id == org_id, User.active))
    if manager is None:
        raise Invalid("The manager must be an active member of this workspace.")
    return manager.id


def _clean_department(department: str | None) -> str | None:
    department = (department or "").strip()
    return department[:80] or None


def invite_many(db: Session, admin: User, *, emails: list[str], role: str, approval_limit: Any = 0,
                manager_id: uuid.UUID | None = None, department: str | None = None) -> list[dict[str, Any]]:
    """Invite several people with the same role. Returns one result per email; links appear only here."""
    _require_admin(admin)
    role, limit = _clean_role(role), _clean_limit(approval_limit)
    manager_id, department = _clean_manager(db, admin.org_id, manager_id), _clean_department(department)
    cleaned: list[str] = []
    for raw in emails:
        email = (raw or "").strip().lower()
        if email and email not in cleaned:
            cleaned.append(email)
    if not cleaned:
        raise Invalid("Enter at least one email address.")
    if len(cleaned) > MAX_BATCH:
        raise Invalid(f"Invite up to {MAX_BATCH} people at a time.")

    results: list[dict[str, Any]] = []
    to_invite: list[str] = []
    for email in cleaned:
        if "@" not in email or "." not in email.split("@")[-1] or len(email) > 320 or " " in email:
            results.append({"email": email, "status": "invalid", "message": "This is not an email address."})
        elif db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
            # Login is by email alone, so one email can hold only one Orrfin account.
            results.append({"email": email, "status": "exists", "message": "This email already has an Orrfin account."})
        elif db.scalar(_pending_invites(admin.org_id).where(TeamInvite.email == email)) is not None:
            results.append({"email": email, "status": "already_invited",
                            "message": "Already invited. Resend the invitation from Pending invites."})
        else:
            to_invite.append(email)
    if role in POWER_ROLES:
        _require_seats(db, admin.org_id, len(to_invite))

    org = db.get(Org, admin.org_id)
    for email in to_invite:
        token = secrets.token_urlsafe(32)
        invite = TeamInvite(id=uuid.uuid4(), org_id=admin.org_id, email=email, role=role, approval_limit=limit,
                            manager_id=manager_id, department=department, token_hash=token_hash(token),
                            invited_by_id=admin.id, expires_at=_now() + timedelta(days=INVITE_DAYS))
        db.add(invite)
        db.flush()
        _audit(db, org_id=admin.org_id, entity_type="team_invite", entity_id=invite.id, actor_id=admin.id,
               action="member_invited", payload={"email": email, "role": role, "approval_limit": limit,
                                                 "department": department})
        # Local email is only a log line (no mail server, synthetic data only); the link is not logged.
        log.info("EMAIL (console sender) to=%s subject=%s invited you to %s on Orrfin", email, admin.full_name,
                 org.name)
        results.append({"email": email, "status": "invited", "invite_id": invite.id, "invite_link": invite_link(token),
                        "expires_at": invite.expires_at})
    db.flush()
    return results


def _load_invite(db: Session, admin: User, invite_id: uuid.UUID) -> TeamInvite:
    _require_admin(admin)
    invite = db.scalar(select(TeamInvite).where(TeamInvite.id == invite_id, TeamInvite.org_id == admin.org_id)
                       .with_for_update())
    if invite is None:
        raise NotFound("Invitation not found.")
    return invite


def resend(db: Session, admin: User, invite_id: uuid.UUID) -> dict[str, Any]:
    """A fresh link with a new 7 days. The old link stops working at once."""
    invite = _load_invite(db, admin, invite_id)
    status = _invite_status(invite)
    if status in ("accepted", "revoked"):
        raise Conflict(f"This invitation was {status}. Send a new one instead.")
    if status == "expired" and invite.role in POWER_ROLES:
        _require_seats(db, admin.org_id, 1)  # an expired invite no longer holds its seat
    token = secrets.token_urlsafe(32)
    invite.token_hash, invite.expires_at = token_hash(token), _now() + timedelta(days=INVITE_DAYS)
    _audit(db, org_id=admin.org_id, entity_type="team_invite", entity_id=invite.id, actor_id=admin.id,
           action="invite_resent", payload={"email": invite.email})
    log.info("EMAIL (console sender) to=%s subject=Reminder: your Orrfin invitation", invite.email)
    db.flush()
    return {**_invite_dict(invite, _names(db, {invite.manager_id, invite.invited_by_id})),
            "invite_link": invite_link(token)}


def revoke(db: Session, admin: User, invite_id: uuid.UUID) -> None:
    invite = _load_invite(db, admin, invite_id)
    if invite.used_at is not None:
        raise Conflict("This invitation was already accepted. Deactivate the member instead.")
    if invite.revoked_at is None:
        invite.revoked_at = _now()
        _audit(db, org_id=admin.org_id, entity_type="team_invite", entity_id=invite.id, actor_id=admin.id,
               action="invite_revoked", payload={"email": invite.email})


# --- Changing members -------------------------------------------------------------------------------

def update_member(db: Session, admin: User, user_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    """Change role, approval limit, manager or department. `changes` holds only the fields being set."""
    member = _load_member(db, admin, user_id, lock=True)
    before = {"role": member.role, "approval_limit": member.approval_limit, "manager_id": member.manager_id,
              "department": member.department}
    if "role" in changes and changes["role"] != member.role:
        new_role = _clean_role(changes["role"])
        if member.id == admin.id:
            raise Forbidden("You can't change your own role. Ask another admin.")
        if member.role == "admin" and member.active and _active_admins(db, admin.org_id) <= 1:
            raise Conflict("This is the last admin. Make someone else an admin first.")
        if member.active and new_role in POWER_ROLES and member.role not in POWER_ROLES:
            _require_seats(db, admin.org_id, 1)
        member.role = new_role
    if "approval_limit" in changes:
        limit = _clean_limit(changes["approval_limit"])
        if member.id == admin.id and limit != member.approval_limit:
            # Segregation of duties: nobody raises (or sets) the ceiling on their own approvals.
            raise Forbidden("You can't change your own approval limit. Ask another admin.")
        member.approval_limit = limit
    if "manager_id" in changes:
        manager_id = _clean_manager(db, admin.org_id, changes["manager_id"])
        if manager_id == member.id:
            raise Invalid("A person can't be their own manager.")
        member.manager_id = manager_id
    if "department" in changes:
        member.department = _clean_department(changes["department"])
    after = {k: getattr(member, k) for k in before}
    changed = {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}
    if changed:
        _audit(db, org_id=admin.org_id, entity_type="user", entity_id=member.id, actor_id=admin.id,
               action="member_updated", payload={"changes": changed})
    db.flush()
    return member_detail(db, admin, member.id)


def deactivate(db: Session, admin: User, user_id: uuid.UUID) -> dict[str, Any]:
    member = _load_member(db, admin, user_id, lock=True)
    if member.id == admin.id:
        raise Forbidden("You can't deactivate yourself. Ask another admin.")
    if not member.active:
        raise Conflict("This member is already deactivated.")
    if member.role == "admin" and _active_admins(db, admin.org_id) <= 1:
        raise Conflict("This is the last admin. Make someone else an admin first.")
    member.active = False
    # Sign them out everywhere now, not when their session would have expired.
    db.execute(delete(UserSession).where(UserSession.user_id == member.id))
    work = open_work(db, member)
    _audit(db, org_id=admin.org_id, entity_type="user", entity_id=member.id, actor_id=admin.id,
           action="member_deactivated", payload={"open_work": work})
    db.flush()
    return member_detail(db, admin, member.id)


def reactivate(db: Session, admin: User, user_id: uuid.UUID) -> dict[str, Any]:
    member = _load_member(db, admin, user_id, lock=True)
    if member.active:
        raise Conflict("This member is already active.")
    if member.role in POWER_ROLES:
        _require_seats(db, admin.org_id, 1)
    member.active = True
    _audit(db, org_id=admin.org_id, entity_type="user", entity_id=member.id, actor_id=admin.id,
           action="member_reactivated")
    db.flush()
    return member_detail(db, admin, member.id)


# --- Accepting (no session yet) -----------------------------------------------------------------------

_NOT_VALID = "This invitation link is not valid any more. Ask your admin to send a new one."


def _usable_invite(db: Session, token: str, *, lock: bool = False) -> TeamInvite:
    query = select(TeamInvite).where(TeamInvite.token_hash == token_hash(token or ""))
    invite = db.scalar(query.with_for_update() if lock else query)
    # Unknown, used, revoked and expired links all get the same answer.
    if invite is None or _invite_status(invite) != "pending":
        raise Invalid(_NOT_VALID)
    return invite


def lookup(db: Session, token: str) -> dict[str, Any]:
    """What the join page shows before the person sets a password."""
    invite = _usable_invite(db, token)
    org = db.get(Org, invite.org_id)
    inviter = db.get(User, invite.invited_by_id)
    return {"email": invite.email, "role": invite.role, "role_name": ROLE_NAMES[invite.role], "org_name": org.name,
            "invited_by_name": inviter.full_name if inviter else None, "department": invite.department,
            "expires_at": invite.expires_at, "needs_mfa": invite.role in ("admin", "finance")}


def accept(db: Session, token: str, *, full_name: str, password: str) -> User:
    """Use an invitation once: create the member's login with the role the admin chose."""
    full_name = (full_name or "").strip()
    if not full_name:
        raise Invalid("Enter your full name.")
    if len(password or "") < MIN_PASSWORD or len(password) > 200:
        raise Invalid(f"Choose a password of at least {MIN_PASSWORD} characters.")
    invite = _usable_invite(db, token, lock=True)
    if db.scalar(select(User.id).where(func.lower(User.email) == invite.email)) is not None:
        raise Conflict("This email already has an Orrfin account. Sign in instead.")
    manager_id = invite.manager_id
    if manager_id and db.scalar(select(User.id).where(User.id == manager_id, User.active)) is None:
        manager_id = None  # the manager left after the invitation was sent
    member = User(id=uuid.uuid4(), org_id=invite.org_id, email=invite.email, full_name=full_name[:200],
                  password_hash=hash_password(password), role=invite.role, approval_limit=invite.approval_limit,
                  manager_id=manager_id, department=invite.department, invited_by_id=invite.invited_by_id)
    db.add(member)
    db.flush()
    invite.used_at = _now()
    _audit(db, org_id=invite.org_id, entity_type="user", entity_id=member.id, actor_id=member.id,
           action="member_joined", payload={"invite_id": invite.id, "role": invite.role})
    notify(db, org_id=invite.org_id, user_id=invite.invited_by_id, kind="team",
           title=f"{member.full_name} joined Orrfin as {ROLE_NAMES[member.role]}", link="/settings/team")
    db.flush()
    return member
