"""Command-line twin of the Connectors page buttons (PROMPTS Steps 13-20; BUILD_PLAN §4).

Runs "Test connection" and then "Prepare demo data" for one ERP connection of the demo org, using the keys
already saved (encrypted) on the Connectors page. It never takes keys on the command line, so they can't
end up in shell history. Prints what was created; never prints a credential.

Run from the repo root:
  backend\\.venv\\Scripts\\python backend\\scripts\\prepare_erp.py --system erpnext --mode live
  backend\\.venv\\Scripts\\python backend\\scripts\\prepare_erp.py --system odoo --mode live --activate
"""

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.adapters.registry import CATALOGUE  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ErpConnection, Org  # noqa: E402
from app.modules.connectors import service  # noqa: E402
from app.seed_demo import ORG_NAME  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", choices=sorted(CATALOGUE), required=True)
    parser.add_argument("--mode", choices=["simulated", "live"], default="live")
    parser.add_argument("--activate", action="store_true", help="make it the active ERP afterwards")
    args = parser.parse_args()

    with SessionLocal() as db:
        org = db.scalar(select(Org).where(Org.name == ORG_NAME))
        if org is None:
            print("Demo org not found. Run scripts/dev.ps1 once first.")
            return 1
        service.ensure_connections(db, org.id)
        connection = db.scalar(select(ErpConnection).where(
            ErpConnection.org_id == org.id, ErpConnection.system == args.system, ErpConnection.mode == args.mode))
        if connection is None:
            print(f"No {args.mode} connection for {args.system}. Save its keys on the Connectors page first.")
            return 1
        check = service.run_connection_test(db, connection, actor_id=None)
        for step in check.steps:
            print(f"  [{'ok' if step.ok else '!!'}] {step.name}: {step.detail}")
        if not check.ok:
            db.commit()
            print(f"Test connection failed: {connection.last_error or 'see above'}")
            return 1
        report = service.prepare_demo_data(db, connection, actor_id=None)
        print("Created:", ", ".join(f"{n} {k}" for k, n in report.created.items()) or "nothing new")
        for note in report.notes:
            print(" -", note)
        if args.activate:
            service.activate(db, connection, actor_id=None)
            print(f"{CATALOGUE[args.system].name} ({args.mode}) is now the active ERP.")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
