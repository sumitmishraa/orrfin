"""Background jobs in Postgres (BUILD_PLAN §3 "Background work", §4 worker).

A job row is claimed with SELECT ... FOR UPDATE SKIP LOCKED, so two workers never take
the same job. A job that fails is retried with backoff up to `max_attempts`, then marked
failed with its error. A job left "running" by a crashed worker is taken again after
STALE_AFTER, so killing the worker mid-job never loses work (§11 M3).

Handlers do their database work in the same transaction that marks the job done, so a
job's effects and its "done" status are committed together or not at all.
"""

import logging
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Job

log = logging.getLogger("orrfin.jobs")

STALE_AFTER = timedelta(minutes=10)
Handler = Callable[[Session, Job], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    """Register a function as the handler for one job kind."""
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return register


def enqueue(db: Session, *, org_id: uuid.UUID, kind: str, payload: dict[str, Any] | None = None,
            created_by: uuid.UUID | None = None) -> Job:
    """Add a job. The caller commits, usually together with the change that needs it."""
    job = Job(org_id=org_id, kind=kind, payload=payload or {}, created_by=created_by,
              run_after=datetime.now(UTC))
    db.add(job)
    db.flush()
    return job


def _claim_next(db: Session) -> Job | None:
    now = datetime.now(UTC)
    job = db.scalar(
        select(Job)
        .where(or_(
            (Job.status == "queued") & (Job.run_after <= now),
            (Job.status == "running") & (Job.updated_at < now - STALE_AFTER),
        ))
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    db.commit()
    return job


def run_next(db: Session) -> Job | None:
    """Claim and run one job. Returns the job, or None if nothing was waiting."""
    job = _claim_next(db)
    if job is None:
        return None
    try:
        fn = HANDLERS.get(job.kind)
        if fn is None:
            raise LookupError(f"No handler registered for job kind '{job.kind}'")
        result = fn(db, job)
        job.status, job.result, job.last_error = "done", result, None
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # any failure is recorded on the job, never swallowed
        db.rollback()
        job = db.get(Job, job.id)
        job.last_error = f"{type(exc).__name__}: {exc}"
        if job.attempts >= job.max_attempts:
            job.status, job.finished_at = "failed", datetime.now(UTC)
        else:
            # Back off 5 s, 10 s, 20 s ... so a flaky ERP isn't hammered.
            job.status = "queued"
            job.run_after = datetime.now(UTC) + timedelta(seconds=5 * 2 ** (job.attempts - 1))
        db.commit()
        log.warning("Job %s (%s) attempt %s failed: %s\n%s", job.id, job.kind, job.attempts,
                    job.last_error, traceback.format_exc())
    return job


def drain(db: Session) -> int:
    """Run every job that is due now (tests and one-off scripts). Returns how many ran."""
    count = 0
    while run_next(db) is not None:
        count += 1
    return count
