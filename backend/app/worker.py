"""Worker process: runs queued jobs (BUILD_PLAN §4 worker: erp_pull now; extract and erp_push later).

Run:  backend\\.venv\\Scripts\\python -m app.worker   (scripts/dev.ps1 starts it for you)
"""

import logging
import time

from app import job_handlers  # noqa: F401  (registers every job handler)
from app.db import SessionLocal
from app.jobs import run_next

POLL_SECONDS = 1.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("orrfin.worker")
    log.info("Worker started; polling for jobs every %.0f s", POLL_SECONDS)
    while True:
        try:
            with SessionLocal() as db:
                job = run_next(db)
            if job is not None:
                log.info("Job %s (%s) -> %s", job.id, job.kind, job.status)
                continue
        except Exception:  # e.g. Postgres restarting: log, wait, try again
            log.exception("Worker loop error; retrying shortly")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
