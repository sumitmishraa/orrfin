"""Demo seed: one org, five users, three categories and the §9 approval tiers (PROMPTS Step 3).

Safe to run repeatedly: existing rows are found by name/email and left as they are,
so demo requests created in the app survive a re-run. All people and data are fictional.
Demo passwords are listed in the README; they are for the local, synthetic demo only.

Run:  backend\\.venv\\Scripts\\python -m app.seed_demo   (scripts/dev.ps1 runs it for you)
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models import ApprovalPolicy, Category, Org, User

ORG_NAME = "Orrfin Demo Co"
DEMO_PASSWORD = "Orrfin@Demo2026"

# (email, name, role, approval limit). The requester's manager is the approver (set below).
USERS = [
    ("riya.requester@demo.orrfin.ai", "Riya Sharma", "requester", "0"),
    ("arjun.buyer@demo.orrfin.ai", "Arjun Mehta", "buyer", "0"),
    ("neha.approver@demo.orrfin.ai", "Neha Iyer", "approver", "500000"),
    ("vikram.finance@demo.orrfin.ai", "Vikram Rao", "finance", "5000000"),
    ("anita.admin@demo.orrfin.ai", "Anita Desai", "admin", "10000000"),
]
CATEGORIES = ["IT hardware", "Office supplies", "Professional services"]
# §9 demo tiers, to be confirmed by the founder (BUILD_PLAN §14 Q7).
POLICIES = [
    (Decimal("0.00"), Decimal("50000.00"), ["manager"]),
    (Decimal("50000.01"), Decimal("500000.00"), ["manager", "finance"]),
    (Decimal("500000.01"), None, ["manager", "finance", "admin"]),
]


def seed(db: Session) -> Org:
    org = db.scalar(select(Org).where(Org.name == ORG_NAME))
    if org is None:
        org = Org(name=ORG_NAME)
        db.add(org)
        db.flush()

    password_hash = hash_password(DEMO_PASSWORD)
    users: dict[str, User] = {}
    for email, name, role, limit in USERS:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            user = User(org_id=org.id, email=email, full_name=name, role=role,
                        approval_limit=Decimal(limit), password_hash=password_hash)
            db.add(user)
        users[role] = user
    db.flush()
    if users["requester"].manager_id is None:
        users["requester"].manager_id = users["approver"].id

    for name in CATEGORIES:
        if db.scalar(select(Category).where(Category.org_id == org.id, Category.name == name)) is None:
            db.add(Category(org_id=org.id, name=name, buyer_id=users["buyer"].id))

    if db.scalar(select(func.count()).select_from(ApprovalPolicy).where(ApprovalPolicy.org_id == org.id)) == 0:
        for low, high, steps in POLICIES:
            db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))

    db.commit()
    return org


def main() -> None:
    with SessionLocal() as db:
        org = seed(db)
    print(f"Seeded '{org.name}' with {len(USERS)} users, {len(CATEGORIES)} categories, {len(POLICIES)} approval tiers.")


if __name__ == "__main__":
    main()
