"""Tell a person that something needs them or happened to their work (BUILD_PLAN v3.0 §5).

A notification is a row for one user: it shows under the bell and is copied to email. Locally
the email is only written to the log (no mail server, no real addresses: synthetic data only);
a real sender is plugged in at deploy time. A notification informs; it never approves, pays or
changes anything, and its link is always a path inside Orrfin.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Notification, User

log = logging.getLogger("orrfin.email")
PAGE = 50


def notify(db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, kind: str, title: str, body: str = "",
           link: str | None = None) -> Notification | None:
    """Add a notification in the caller's transaction. Skips a user who is not in this org."""
    user = db.scalar(select(User).where(User.id == user_id, User.org_id == org_id, User.active))
    if user is None:
        return None
    if link is not None and not (link.startswith("/") and not link.startswith("//")):
        # Only paths inside the app: a notification must never carry a link to another site.
        link = None
    row = Notification(org_id=org_id, user_id=user_id, kind=kind[:40], title=title[:200], body=body, link=link)
    db.add(row)
    db.flush()
    log.info("EMAIL (console sender) to=%s subject=%s", user.email, row.title)
    return row


def as_dict(row: Notification) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "title": row.title, "body": row.body, "link": row.link,
            "read": row.read_at is not None, "at": row.created_at}


def inbox(db: Session, user: User) -> dict[str, Any]:
    """The user's own latest notifications and how many are unread. Never anyone else's."""
    mine = (Notification.user_id == user.id) & (Notification.org_id == user.org_id)
    rows = db.scalars(select(Notification).where(mine).order_by(Notification.created_at.desc()).limit(PAGE))
    unread = db.scalar(select(func.count()).select_from(Notification).where(mine, Notification.read_at.is_(None)))
    return {"unread": unread or 0, "items": [as_dict(r) for r in rows]}


def mark_read(db: Session, user: User, notification_id: uuid.UUID | None = None) -> int:
    """Mark one notification (or all of them) read. Only the user's own rows are touched."""
    query = update(Notification).where(Notification.user_id == user.id, Notification.org_id == user.org_id,
                                       Notification.read_at.is_(None))
    if notification_id is not None:
        query = query.where(Notification.id == notification_id)
    return db.execute(query.values(read_at=datetime.now(UTC))).rowcount
