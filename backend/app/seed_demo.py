"""Demo seed: one org, its users, categories, the §9 approval tiers, the ERP connection rows
(PROMPTS Steps 3 and 12) and the Step 22 workflow data: a "Software & SaaS" category with an
IT security review step, and this quarter's budgets per cost centre.

Step 42 (ADR 0012): the demo org follows the need-first order: the employee states a need, the General
Manager approves it, procurement (Arjun) builds one PO per vendor from the approved needs, Finance approves
POs above ₹50,000, and the PO is sent to the vendor (simulated). A second employee (Sameer) and three
needs show it straight away: two approved and waiting for procurement, one waiting for the manager.

Safe to run repeatedly: existing rows are found by name/email and left as they are,
so demo requests created in the app survive a re-run. All people and data are fictional.
Demo passwords are listed in the README; they are for the local, synthetic demo only.

Run:  backend\\.venv\\Scripts\\python -m app.seed_demo   (scripts/dev.ps1 runs it for you)
"""

import os
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models import (
    ApprovalPolicy,
    Budget,
    Category,
    Org,
    PurchaseRequest,
    TeamInvite,
    User,
    Vendor,
    VendorPaymentProfile,
)
from app.modules.connectors.service import ensure_connections
from app.modules.workflows.budgets import quarter_of, today_ist

ORG_NAME = "Orrfin Demo Co"
# A public demo server sets ORRFIN_DEMO_PASSWORD so the password printed in the README does not open it.
# Only users created by this seed get it; existing users keep theirs.
DEMO_PASSWORD = os.environ.get("ORRFIN_DEMO_PASSWORD") or "Orrfin@Demo2026"

# (email, name, role, approval limit). The requester's manager is the approver (set below).
USERS = [
    ("riya.requester@demo.orrfin.ai", "Riya Sharma", "requester", "0"),
    ("arjun.buyer@demo.orrfin.ai", "Arjun Mehta", "buyer", "0"),
    ("neha.approver@demo.orrfin.ai", "Neha Iyer", "approver", "500000"),
    ("vikram.finance@demo.orrfin.ai", "Vikram Rao", "finance", "5000000"),
    ("anita.admin@demo.orrfin.ai", "Anita Desai", "admin", "10000000"),
]
# Step 41: departments on the Team page, one person who left, and one invitation still waiting.
DEPARTMENTS = {"requester": "Operations", "buyer": "Procurement", "approver": "General Management",
               "finance": "Finance", "admin": "Finance"}
# Step 42: a second employee who reports to the General Manager (Neha).
SECOND_REQUESTER = ("sameer.requester@demo.orrfin.ai", "Sameer Joshi", "requester", "Operations")
# (who, title, [(description, qty, unit)], channel, message, approved by the manager)
NEEDS = [
    ("requester", "A4 paper for the Pune office", [("A4 copier paper, 75 gsm, box of 5 reams", "20", "box")],
     "whatsapp", "Hi Neha, we need 20 boxes of A4 paper for the Pune office in the next two weeks. Thanks, Riya",
     True),
    ("sameer", "Stationery for the operations desk",
     [("A4 copier paper, 75 gsm, box of 5 reams", "10", "box"), ("Box file, foolscap", "5", "pcs")],
     "email", "Dear Neha,\nPlease arrange 10 boxes of A4 paper and 5 box files for the operations desk.\n"
              "Regards,\nSameer", True),
    ("sameer", "Blue pens for the new joiners", [("Blue ball pens, box of 50", "4", "box")], "form", None, False),
]
FORMER_MEMBER = ("rahul.former@demo.orrfin.ai", "Rahul Verma", "buyer", "Procurement")
PENDING_INVITE = ("pooja.newhire@demo.orrfin.ai", "approver", "Marketing")
CATEGORIES = ["IT hardware", "Office supplies", "Professional services"]
# Step 22: a named reviewer outside the amount tiers (Zip's "vendor touches data → security review").
SECURITY_LEAD = ("kabir.security@demo.orrfin.ai", "Kabir Khan", "approver", "0")
SOFTWARE_CATEGORY = ("Software & SaaS", "IT security review")
# Step 22: budgets for the current financial-year quarter, per cost centre (warnings only).
# Step 25: synthetic vendor payment details that show each payment-risk path in the demo.
# (vendor name starts with, PAN, TDS section, payee type, account, IFSC, verified, days since bank change)
PAYMENT_PROFILES = [
    ("Shreeji", "AABCS4821K", "194C", "company", "50200012345678", "HDFC0001234", True, 200),
    ("Kaveri", "AAKFK3310P", "194Q", "company", "91101000456789", "ICIC0004567", True, 5),   # recent change → hold
    ("Sahyadri", "ABNPS1204H", "194C", "individual", "32011122334455", "ORFN0000000", True, 300),  # mock bank rejects
    ("Deccan", None, "194C", "company", "60011223344556", "SBIN0007788", True, 400),  # no PAN → 206AA rate
    ("Northwind", "AADCN5566Q", "194J", "company", "78900011122233", "UTIB0001122", False, 2),  # unverified → block
]
BUDGETS = {"IT-OPS": Decimal("1000000.00"), "FIN-OPS": Decimal("300000.00"),
           "ADMIN": Decimal("200000.00"), "MARKETING": Decimal("500000.00")}
# §9 demo tiers, to be confirmed by the founder (BUILD_PLAN §14 Q7).
POLICIES = [
    (Decimal("0.00"), Decimal("50000.00"), ["manager"]),
    (Decimal("50000.01"), Decimal("500000.00"), ["manager", "finance"]),
    (Decimal("500000.01"), None, ["manager", "finance", "admin"]),
]


def _seed_team(db: Session, org: Org, users: dict[str, User], password_hash: str, security: User) -> None:
    for role, user in users.items():
        if user.department is None or (role == "approver" and user.department == "Operations"):
            user.department = DEPARTMENTS[role]  # Step 42: Neha is the General Manager
    if security.department is None:
        security.department = "IT"
    email, name, role, department = FORMER_MEMBER
    if db.scalar(select(User).where(func.lower(User.email) == email)) is None:
        db.add(User(org_id=org.id, email=email, full_name=name, role=role, department=department, active=False,
                    password_hash=password_hash, invited_by_id=users["admin"].id))
    email, role, department = PENDING_INVITE
    if db.scalar(select(TeamInvite).where(TeamInvite.email == email)) is None:
        # The raw token is thrown away: the admin can "Resend" from the Team page to get a working link.
        db.add(TeamInvite(org_id=org.id, email=email, role=role, department=department,
                          approval_limit=Decimal("100000"), manager_id=users["finance"].id,
                          token_hash=secrets.token_hex(32), invited_by_id=users["admin"].id,
                          expires_at=datetime.now(UTC) + timedelta(days=7)))


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

    email, name, role, limit = SECURITY_LEAD
    security = db.scalar(select(User).where(func.lower(User.email) == email))
    if security is None:
        security = User(org_id=org.id, email=email, full_name=name, role=role, approval_limit=Decimal(limit),
                        password_hash=password_hash)
        db.add(security)
        db.flush()
    software_name, software_step = SOFTWARE_CATEGORY
    if db.scalar(select(Category).where(Category.org_id == org.id, Category.name == software_name)) is None:
        db.add(Category(org_id=org.id, name=software_name, buyer_id=users["buyer"].id,
                        extra_approver_id=security.id, extra_step_label=software_step))

    fy, quarter = quarter_of(today_ist())
    for cost_center, amount in BUDGETS.items():
        if db.scalar(select(Budget).where(Budget.org_id == org.id, Budget.cost_center == cost_center,
                                          Budget.fiscal_year == fy, Budget.quarter == quarter)) is None:
            db.add(Budget(org_id=org.id, cost_center=cost_center, fiscal_year=fy, quarter=quarter, amount=amount))

    _seed_payment_profiles(db, org, users)
    _seed_team(db, org, users, password_hash, security)
    org.intake_flow = "need_first"  # Step 42: need → General Manager → procurement → PO → vendor

    if db.scalar(select(func.count()).select_from(ApprovalPolicy).where(ApprovalPolicy.org_id == org.id)) == 0:
        for low, high, steps in POLICIES:
            db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))

    # One connection row per catalogue ERP; simulated ERPNext is active until the admin picks another.
    ensure_connections(db, org.id)

    db.commit()
    _first_erp_sync(db, org, users)
    _seed_needs(db, org, users, password_hash)
    return org


def _first_erp_sync(db: Session, org: Org, users: dict[str, User]) -> None:
    """A brand-new server (Step 28) has no vendors, POs or item codes until someone presses
    "Sync from ERP". Pull once from the active (simulated) ERP so the demo works straight away, then
    add the payment profiles that need those vendors. A laptop that has synced already is untouched."""
    if db.scalar(select(func.count()).select_from(Vendor).where(Vendor.org_id == org.id)):
        return
    from app.adapters.registry import get_adapter  # local imports: keep the seed light for tests
    from app.modules.connectors.service import active_connection
    from app.modules.sync.service import pull_from_erp

    connection = active_connection(db, org.id)
    pull_from_erp(db, org.id, get_adapter(connection), connection.id)
    db.commit()
    _seed_payment_profiles(db, org, users)
    db.commit()


def _seed_needs(db: Session, org: Org, users: dict[str, User], password_hash: str) -> None:
    """Step 42: a second employee and three needs, created through the same service calls the app uses,
    so each has its normal audit trail. Skipped once a need with the same title exists."""
    from app.modules.procurement import service as procurement  # local import: keeps the seed light for tests

    email, name, role, department = SECOND_REQUESTER
    sameer = db.scalar(select(User).where(func.lower(User.email) == email))
    if sameer is None:
        sameer = User(org_id=org.id, email=email, full_name=name, role=role, department=department,
                      manager_id=users["approver"].id, password_hash=password_hash, invited_by_id=users["admin"].id)
        db.add(sameer)
        db.commit()
    people = {"requester": users["requester"], "sameer": sameer}
    office = db.scalar(select(Category).where(Category.org_id == org.id, Category.name == "Office supplies"))
    needed_by = today_ist() + timedelta(days=14)
    for who, title, lines, channel, message, approve in NEEDS:
        person = people[who]
        if db.scalar(select(PurchaseRequest.id).where(PurchaseRequest.org_id == org.id,
                                                      PurchaseRequest.requested_by == person.id,
                                                      PurchaseRequest.title == title)):
            continue
        request = procurement.create_request(
            db, person, category_id=office.id, title=title, justification="Monthly office requirement.",
            cost_center="ADMIN", needed_by=needed_by, source_channel=channel, source_message=message,
            lines=[procurement.LineInput(description=d, qty=Decimal(q), est_rate=Decimal("0"), unit=u)
                   for d, q, u in lines])
        procurement.submit_request(db, person, request.id)
        if approve:
            procurement.decide(db, users["approver"], request.id, 1, "approve", None)
        db.commit()


def _seed_payment_profiles(db: Session, org: Org, users: dict[str, User]) -> None:
    """Payment details for the mirrored vendors (only once the ERP sync has brought them in)."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    for prefix, pan, section, payee, account, ifsc, verified, days in PAYMENT_PROFILES:
        vendor = db.scalar(select(Vendor).where(Vendor.org_id == org.id, Vendor.name.ilike(f"{prefix}%")).limit(1))
        if vendor is None or db.scalar(select(VendorPaymentProfile.id).where(
                VendorPaymentProfile.org_id == org.id, VendorPaymentProfile.vendor_id == vendor.id)):
            continue
        db.add(VendorPaymentProfile(
            org_id=org.id, vendor_id=vendor.id, pan=pan, tds_section=section, payee_type=payee,
            account_name=vendor.name, bank_account=account, ifsc=ifsc,
            status="verified" if verified else "pending_verification", changed_by=users["finance"].id,
            changed_at=now - timedelta(days=days), verified_by=users["admin"].id if verified else None,
            verified_at=now - timedelta(days=days) if verified else None))


def main() -> None:
    with SessionLocal() as db:
        org = seed(db)
    print(f"Seeded '{org.name}' with {len(USERS) + 2} users, {len(CATEGORIES) + 1} categories, "
          f"{len(POLICIES)} approval tiers and {len(BUDGETS)} budgets for this quarter.")


if __name__ == "__main__":
    main()
