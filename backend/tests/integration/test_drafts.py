"""AI drafts around the workflows (BUILD_PLAN v2.3 change 26, v2.4 change 33; PROMPTS Step 24).

Done when: rates are never AI-guessed (last paid PO price or blank); the approval chain shown is the
one the server will enforce; a drafted request still blocks self-approval and its audit event says it
was drafted by AI; notes and "what changed" fall back to templates without AI or when a ₹ figure strays.
"""

from datetime import timedelta

from sqlalchemy import select

from app import job_handlers  # noqa: F401
from app.adapters.fake_assistant import FakeDrafter
from app.models import ApprovalPolicy, AuditEvent, Category
from app.modules.invoices.providers import use_drafter
from app.modules.workflows.budgets import today_ist
from app.seed_demo import POLICIES
from tests.conftest import login
from tests.integration.test_invoice_review import _matched, team  # noqa: F401  (fixture)
from tests.integration.test_procurement import _complete_and_send, _decide, _new_request, world  # noqa: F401


def _categories(db, org):
    for name in ("IT hardware", "Office supplies"):
        db.add(Category(org_id=org.id, name=name))
    for low, high, steps in POLICIES:
        db.add(ApprovalPolicy(org_id=org.id, min_amount=low, max_amount=high, steps=steps))
    db.commit()


def _draft(client, user, drafter, text="5 laptops and 5 chairs for the Pune hires"):
    login(client, user)
    with use_drafter(drafter):
        return client.post("/assistant/draft-request", json={"text": text}).json()


LAPTOPS = {"title": "Laptops for Pune hires", "justification": "New analysts", "category": "IT hardware",
           "cost_center": "fin-ops", "needed_by": "", "lines": [
               {"description": "Laptop 14in Core i5", "qty": "5"},
               {"description": "Ergonomic chair", "qty": "5"}]}


def test_rates_come_from_the_last_paid_po_never_from_the_ai(client, db, team, factory):  # noqa: F811
    _categories(db, team.org)
    requester = factory.user(team.org, "requester", manager=team.reviewer, name="Riya")
    needed = (today_ist() + timedelta(days=14)).isoformat()
    draft = _draft(client, requester, FakeDrafter({**LAPTOPS, "needed_by": needed}))
    assert draft["available"] is True
    laptop, chair = draft["draft"]["lines"]
    assert laptop["est_rate"] == "78500.00" and "PUR-ORD-2026-00002" in laptop["rate_source"]
    assert chair["est_rate"] is None and "please enter the rate" in chair["rate_source"]
    assert draft["amount"] == "392500.00" and draft["all_priced"] is False
    assert draft["approval_chain"] == ["Requester's manager", "Finance"]  # ₹3,92,500 → two steps
    assert draft["draft"]["cost_center"] == "FIN-OPS" and draft["draft"]["needed_by"] == needed
    assert draft["ai_draft"]["prompt_version"] == "draft-v1"


def test_an_unknown_category_bad_output_or_no_ai_leaves_the_form_to_the_person(client, db, team, factory):  # noqa: F811
    _categories(db, team.org)
    requester = factory.user(team.org, "requester", manager=team.reviewer)
    assert _draft(client, requester, FakeDrafter({**LAPTOPS, "category": "Yachts"}))["available"] is False
    assert _draft(client, requester, FakeDrafter({"title": ""}))["available"] is False
    assert _draft(client, requester, FakeDrafter(fail=True))["available"] is False
    assert _draft(client, requester, None)["available"] is False  # AI_PROVIDER=fake in tests


def test_a_past_date_is_dropped_with_a_warning(client, db, team, factory):  # noqa: F811
    _categories(db, team.org)
    requester = factory.user(team.org, "requester", manager=team.reviewer)
    draft = _draft(client, requester, FakeDrafter({**LAPTOPS, "needed_by": "2020-01-01"}))
    assert draft["draft"]["needed_by"] is None and any("past" in w for w in draft["warnings"])


def test_a_drafted_request_is_audited_as_ai_drafted_and_still_cannot_be_self_approved(client, db, world):
    login(client, world.requester)
    created = client.post("/requests", json={
        "category_id": str(world.category.id), "title": "Laptops", "cost_center": "FIN-OPS",
        "lines": [{"description": "Laptop", "qty": "1", "est_rate": "40000"}],
        "ai_draft": {"model_id": "gemini-test", "prompt_version": "draft-v1"}})
    assert created.status_code == 201, created.text
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == created.json()["id"],
                                               AuditEvent.action == "created"))
    assert event.payload["drafted_by_ai"] is True and event.payload["model_id"] == "gemini-test"
    submitted = client.post(f"/requests/{created.json()['id']}/submit")
    assert submitted.status_code == 200
    sent = _complete_and_send(client, world, submitted.json())
    assert _decide(client, world.requester, sent["id"], 1).status_code == 403


# --- Exception notes -------------------------------------------------------------------------------------

def test_a_note_is_written_from_the_rule_results_with_a_template_fallback(client, db, team):  # noqa: F811
    invoice_id = _matched(client, db, team.uploader, "02-price-variance-7pct")
    login(client, team.reviewer)
    with use_drafter(None):
        note = client.post(f"/invoices/{invoice_id}/draft-note", json={"audience": "vendor"}).json()
    assert note["source"] == "template (no AI)" and "₹910.00 is on hold" in note["text"]

    good = FakeDrafter(text_out="Dear supplier, the rate is above the PO; ₹910.00 is on hold.")
    with use_drafter(good):
        note = client.post(f"/invoices/{invoice_id}/draft-note", json={"audience": "vendor"}).json()
    assert note["source"].startswith("fake-drafter") and "Check results" in good.seen[0]

    stray = FakeDrafter(text_out="Please refund ₹99,999.00.")
    with use_drafter(stray):
        note = client.post(f"/invoices/{invoice_id}/draft-note", json={"audience": "requester"}).json()
    assert note["source"] == "template (no AI)" and "not in the check results" in note["note"]


# --- "What changed" --------------------------------------------------------------------------------------

def test_what_changed_compares_periods_and_falls_back_without_ai(client, db, world):
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))
    assert _decide(client, world.manager, request["id"], 1).status_code == 200
    login(client, world.finance)
    with use_drafter(None):
        notes = client.post("/insights/notes", params={"period": "month"}).json()
    assert notes["source"] == "template (no AI)"
    assert notes["bullets"][0].startswith("Approved spend this month: ₹40,000.00")
    assert notes["numbers"]["category_changes"][0]["category"] == "IT hardware"

    stray = FakeDrafter(text_out="- Spend rose to ₹1,23,456.00.")
    with use_drafter(stray):
        notes = client.post("/insights/notes", params={"period": "quarter"}).json()
    assert notes["source"] == "template (no AI)"  # a figure not in the numbers is never shown
    good = FakeDrafter(text_out="- IT hardware spend is ₹40,000.00, up from ₹0.00.\n- Nothing is on hold.")
    with use_drafter(good):
        notes = client.post("/insights/notes", params={"period": "month"}).json()
    assert notes["bullets"] == ["IT hardware spend is ₹40,000.00, up from ₹0.00.", "Nothing is on hold."]
