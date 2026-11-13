"""Workflow engine through the API (ADR 0010; BUILD_PLAN §9 v3.0, §11 M9).

What must hold: only admins touch workflows; an unsafe definition cannot go live; a published
version is frozen; lowering approvals needs a second admin; a published workflow chooses a
request's steps but never weakens segregation of duties; nothing leaks across orgs.
"""

from sqlalchemy import select

from app.models import AuditEvent, RequestApproval, WorkflowVersion
from app.modules.audit.service import verify_chain
from tests.conftest import login
from tests.integration.test_procurement import (  # noqa: F401  (world is a fixture)
    World,
    _complete_and_send,
    _decide,
    _new_request,
    world,
)


def two_step(threshold: str = "50000.00") -> dict:
    """Manager always; finance as well above the threshold."""
    return {
        "subject": "request", "start": "mgr",
        "nodes": [
            {"id": "mgr", "kind": "approval", "role": "manager", "next": "big"},
            {"id": "big", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": threshold}, "then": "fin", "else": "end"},
            {"id": "fin", "kind": "approval", "role": "finance", "label": "Finance approval", "next": "end"},
        ],
    }


def like_the_tiers(finance_above: str = "50000.00") -> dict:
    """The same approvals as the built-in tiers: manager; finance above ₹50,000; admin above ₹5,00,000."""
    return {
        "subject": "request", "start": "mgr",
        "nodes": [
            {"id": "mgr", "kind": "approval", "role": "manager", "next": "big"},
            {"id": "big", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": finance_above}, "then": "fin", "else": "end"},
            {"id": "fin", "kind": "approval", "role": "finance", "next": "huge"},
            {"id": "huge", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": "500000.00"}, "then": "adm", "else": "end"},
            {"id": "adm", "kind": "approval", "role": "admin", "next": "end"},
        ],
    }


def manager_only() -> dict:
    return {"subject": "request", "start": "mgr",
            "nodes": [{"id": "mgr", "kind": "approval", "role": "manager", "next": "end"}]}


def _save(client, definition: dict, key: str = "request-approval"):
    return client.post("/workflow-definitions", json={"key": key, "name": "Request approval",
                                                      "definition": definition})


def _publish(client, version_id: str):
    return client.post(f"/workflow-definitions/versions/{version_id}/publish")


def _second_admin(factory, world: World):
    return factory.user(world.org, "admin", limit="10000000", name="Second Admin")


def _chain_roles(db, request_id: str) -> list[str]:
    db.expire_all()
    rows = db.scalars(select(RequestApproval).where(RequestApproval.request_id == request_id)
                      .order_by(RequestApproval.round, RequestApproval.step)).all()
    return [row.required_role for row in rows]


# --- Who may use the builder ---------------------------------------------------------------

def test_only_an_admin_can_read_or_change_workflows(client, world: World):
    for user in (world.requester, world.buyer, world.manager, world.finance):
        login(client, user)
        assert client.get("/workflow-definitions").status_code == 403
        assert _save(client, two_step()).status_code == 403
        assert client.post("/workflow-definitions/check", json={"definition": two_step()}).status_code == 403


def test_another_org_cannot_see_or_publish_a_workflow(client, world: World, factory):
    login(client, world.admin)
    saved = _save(client, two_step()).json()
    outsider = factory.user(factory.org("Other Org"), "admin", limit="1")

    login(client, outsider)

    assert client.get("/workflow-definitions").json() == []
    assert client.get(f"/workflow-definitions/{saved['definition_id']}").status_code == 404
    assert _publish(client, saved["version_id"]).status_code == 404


# --- Saving, checking, simulating ------------------------------------------------------------

def test_a_draft_reports_its_problems_and_cannot_be_published_with_them(client, world: World, factory):
    login(client, world.admin)
    unsafe = two_step()
    unsafe["start"] = "big"  # a small request would finish with no approval at all

    saved = _save(client, unsafe)
    login(client, _second_admin(factory, world))
    published = _publish(client, saved.json()["version_id"])

    assert saved.status_code == 201
    assert any("no approval" in problem for problem in saved.json()["problems"])
    assert published.status_code == 422


def test_a_named_approver_must_be_an_active_user_of_this_org(client, world: World, factory):
    stranger = factory.user(factory.org("Other Org"), "approver")
    definition = manager_only()
    definition["nodes"][0] = {"id": "mgr", "kind": "approval", "approver_id": str(stranger.id), "next": "end"}
    login(client, world.admin)

    problems = client.post("/workflow-definitions/check", json={"definition": definition}).json()["problems"]

    assert problems == ['Step "mgr": the named person is not an active user of this company.']


def test_simulate_shows_the_route_without_saving_anything(client, world: World, db):
    login(client, world.admin)

    small = client.post("/workflow-definitions/simulate",
                        json={"definition": two_step(), "facts": {"amount": "40000.00"}}).json()
    large = client.post("/workflow-definitions/simulate",
                        json={"definition": two_step(), "facts": {"amount": "50000.01"}}).json()

    assert [step["role"] for step in small["approvals"]] == ["manager"]
    assert [step["role"] for step in large["approvals"]] == ["manager", "finance"]
    assert [node["id"] for node in large["route"]] == ["mgr", "big", "fin"]
    assert db.scalar(select(WorkflowVersion.id).where(WorkflowVersion.org_id == world.org.id)) is None


# --- Publishing ----------------------------------------------------------------------------

def test_publishing_is_audited_with_the_version_hash_and_freezes_the_version(client, world: World, db):
    login(client, world.admin)
    # As many approvals as the built-in tiers at every amount, so the admin who drafted it may publish it.
    saved = _save(client, like_the_tiers()).json()

    published = _publish(client, saved["version_id"])
    again = _publish(client, saved["version_id"])

    assert published.status_code == 200 and published.json()["status"] == "published"
    assert again.status_code == 409
    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == saved["definition_id"])
                        .order_by(AuditEvent.seq)).all()
    assert [event.action for event in events] == ["draft_saved", "published"]
    assert events[1].payload["sha256"] == saved["sha256"] == published.json()["sha256"]
    assert verify_chain(db, saved["definition_id"])


def test_a_new_version_retires_the_old_one(client, world: World, db, factory):
    login(client, world.admin)
    first = _save(client, like_the_tiers()).json()
    assert _publish(client, first["version_id"]).status_code == 200
    second = _save(client, like_the_tiers("40000.00")).json()  # stricter: finance from a lower amount

    assert _publish(client, second["version_id"]).status_code == 200

    db.expire_all()
    statuses = {v.number: v.status for v in db.scalars(select(WorkflowVersion).where(
        WorkflowVersion.definition_id == first["definition_id"]))}
    assert statuses == {1: "retired", 2: "published"}


def test_the_admin_who_drafted_fewer_approvals_cannot_publish_them_alone(client, world: World, factory):
    login(client, world.admin)
    weaker = _save(client, manager_only()).json()  # the tiers ask for finance above ₹50,000; this never does

    alone = _publish(client, weaker["version_id"])
    login(client, _second_admin(factory, world))
    with_second_admin = _publish(client, weaker["version_id"])

    assert alone.status_code == 403
    assert "second admin" in alone.json()["detail"]
    assert with_second_admin.status_code == 200


# --- Effect on requests --------------------------------------------------------------------

def test_without_a_published_workflow_the_built_in_tiers_still_apply(client, world: World, db):
    login(client, world.admin)
    _save(client, manager_only())  # a draft only: it must change nothing

    request = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))

    assert _chain_roles(db, request["id"]) == ["manager", "finance"]


def test_a_published_workflow_chooses_the_steps_of_new_requests(client, world: World, db, factory):
    login(client, world.admin)
    definition = two_step("300000.00")  # finance only above ₹3,00,000: weaker than the tiers
    saved = _save(client, definition).json()
    login(client, _second_admin(factory, world))
    assert _publish(client, saved["version_id"]).status_code == 200

    below = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))
    above = _complete_and_send(client, world, _new_request(client, world, amount="400000.00"))

    assert _chain_roles(db, below["id"]) == ["manager"]
    assert _chain_roles(db, above["id"]) == ["manager", "finance"]


def test_a_request_already_in_approval_keeps_its_chain_when_a_workflow_is_published(client, world: World, db, factory):
    running = _complete_and_send(client, world, _new_request(client, world, amount="240000.00"))
    login(client, world.admin)
    saved = _save(client, manager_only()).json()
    login(client, _second_admin(factory, world))
    assert _publish(client, saved["version_id"]).status_code == 200

    assert _chain_roles(db, running["id"]) == ["manager", "finance"]
    assert _decide(client, world.manager, running["id"], 1).json()["status"] == "in_approval"


def test_a_workflow_never_weakens_segregation_of_duties(client, world: World, factory):
    login(client, world.admin)
    saved = _save(client, manager_only()).json()
    login(client, _second_admin(factory, world))
    assert _publish(client, saved["version_id"]).status_code == 200
    request = _complete_and_send(client, world, _new_request(client, world, amount="40000.00"))

    own_request = _decide(client, world.requester, request["id"], 1)
    own_completion = _decide(client, world.buyer, request["id"], 1)
    wrong_person = _decide(client, world.finance, request["id"], 1)
    manager = _decide(client, world.manager, request["id"], 1)

    assert own_request.status_code == 403
    assert own_completion.status_code == 403
    assert wrong_person.status_code == 403
    assert manager.status_code == 200 and manager.json()["status"] == "approved"


def test_dropping_only_the_top_tier_approval_also_needs_a_second_admin(client, world: World):
    """two_step() matches the tiers up to ₹5,00,000 but never asks for the admin above it."""
    login(client, world.admin)
    saved = _save(client, two_step()).json()

    alone = _publish(client, saved["version_id"])

    assert alone.status_code == 403
