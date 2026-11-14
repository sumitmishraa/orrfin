"""Intake forms through the API (BUILD_PLAN v3.0 change 40, §9).

What must hold: only an admin builds a form; answers are checked on the server against the form;
nothing crosses orgs; and a workflow can route on an answer without any control being skipped.
"""

from app.models import PurchaseRequest
from tests.conftest import login
from tests.integration.test_procurement import World, _complete_and_send, world  # noqa: F401  (world is a fixture)
from tests.integration.test_workflow_engine import _publish, _save

SOFTWARE = {
    "key": "software", "name": "Software purchase", "description": "SaaS and licences",
    "fields": [
        {"key": "seats", "label": "Seats", "kind": "number", "required": True},
        {"key": "data_class", "label": "Data handled", "kind": "choice", "required": True,
         "options": ["Public", "Personal data"]},
        {"key": "owner", "label": "Business owner", "kind": "user"},
    ],
}


def _make_type(client, world: World, body: dict = SOFTWARE) -> dict:
    login(client, world.admin)
    created = client.post("/request-types", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _request_body(world: World, **extra) -> dict:
    return {"category_id": str(world.category.id), "title": "Design tool", "justification": "Needed",
            "cost_center": "OPS", "lines": [{"description": "Licences", "qty": "2", "est_rate": "20000.00"}], **extra}


def test_only_an_admin_builds_forms_and_requesters_see_the_ones_in_use(client, world):
    for user in (world.requester, world.buyer, world.finance):
        login(client, user)
        assert client.post("/request-types", json=SOFTWARE).status_code == 403
    software = _make_type(client, world)
    assert [f["key"] for f in software["fields"]] == ["seats", "data_class", "owner"]
    assert client.post("/request-types", json=SOFTWARE).status_code == 409  # the key is taken
    off = client.put(f"/request-types/{software['id']}", json={**SOFTWARE, "active": False})
    assert off.status_code == 200 and off.json()["active"] is False
    assert len(client.get("/request-types").json()) == 1   # the admin still sees it
    login(client, world.requester)
    assert client.get("/request-types").json() == []         # a requester does not
    assert client.put(f"/request-types/{software['id']}", json=SOFTWARE).status_code == 403


def test_a_form_that_makes_no_sense_is_refused(client, world):
    login(client, world.admin)
    for bad_fields in (
        [{"key": "Seats", "label": "Seats", "kind": "number"}],
        [{"key": "a1", "label": "A", "kind": "text"}, {"key": "a1", "label": "B", "kind": "text"}],
        [{"key": "code", "label": "Code", "kind": "script"}],
        [{"key": "tier", "label": "Tier", "kind": "choice", "options": []}],
    ):
        response = client.post("/request-types", json={**SOFTWARE, "fields": bad_fields})
        assert response.status_code == 422, (bad_fields, response.text)
    assert client.post("/request-types", json={**SOFTWARE, "key": "Bad Key"}).status_code == 422


def test_answers_are_checked_against_the_form_and_stored_clean(client, db, world):
    software = _make_type(client, world)
    login(client, world.requester)
    good = client.post("/requests", json=_request_body(
        world, request_type_id=software["id"],
        custom_values={"seats": " 25 ", "data_class": "Public", "owner": str(world.manager.id)}))
    assert good.status_code == 201, good.text
    assert good.json()["custom_values"] == {"seats": "25", "data_class": "Public", "owner": str(world.manager.id)}
    assert good.json()["request_type_name"] == "Software purchase"

    for bad in (
        {"data_class": "Public"},                                   # a required answer is missing
        {"seats": "25", "data_class": "Top secret"},                # not one of the options
        {"seats": 25, "data_class": "Public"},                      # a number, not text
        {"seats": "25", "data_class": "Public", "is_admin": "1"},   # a question the form does not have
        {"seats": "25", "data_class": "Public", "owner": "00000000-0000-0000-0000-000000000001"},
    ):
        response = client.post("/requests", json=_request_body(world, request_type_id=software["id"], custom_values=bad))
        assert response.status_code == 422, (bad, response.text)
    # Answers with no type, and a type that does not exist, are refused too.
    assert client.post("/requests", json=_request_body(world, custom_values={"seats": "1"})).status_code == 422
    assert client.post("/requests", json=_request_body(
        world, request_type_id="00000000-0000-0000-0000-000000000002")).status_code == 422
    assert db.query(PurchaseRequest).filter(PurchaseRequest.org_id == world.org.id).count() == 1


def test_another_orgs_form_and_people_cannot_be_used(client, factory, world):
    software = _make_type(client, world)
    other_org = factory.org("Other org")
    other_admin = factory.user(other_org, "admin", limit="10000000")
    login(client, other_admin)
    assert client.get("/request-types").json() == []
    assert client.put(f"/request-types/{software['id']}", json=SOFTWARE).status_code == 404
    login(client, world.requester)
    stolen_person = client.post("/requests", json=_request_body(
        world, request_type_id=software["id"],
        custom_values={"seats": "1", "data_class": "Public", "owner": str(other_admin.id)}))
    assert stolen_person.status_code == 422


def test_an_edit_replaces_the_answers_only_when_it_names_the_type(client, world):
    software = _make_type(client, world)
    login(client, world.requester)
    request = client.post("/requests", json=_request_body(
        world, request_type_id=software["id"], custom_values={"seats": "5", "data_class": "Public"})).json()
    renamed = client.patch(f"/requests/{request['id']}", json={"title": "Design tool, annual"})
    assert renamed.json()["custom_values"] == {"seats": "5", "data_class": "Public"}  # untouched
    bad = client.patch(f"/requests/{request['id']}", json={"request_type_id": software["id"], "custom_values": {}})
    assert bad.status_code == 422
    cleared = client.patch(f"/requests/{request['id']}", json={"request_type_id": None})
    assert cleared.status_code == 200
    assert (cleared.json()["request_type_id"], cleared.json()["custom_values"]) == (None, None)


def _security_review_workflow() -> dict:
    """The built-in tiers, plus an admin security review when the form says personal data is handled."""
    return {
        "subject": "request", "start": "mgr",
        "nodes": [
            {"id": "mgr", "kind": "approval", "role": "manager", "next": "pd"},
            {"id": "pd", "kind": "condition",
             "when": {"field": "custom.data_class", "op": "==", "value": "Personal data"}, "then": "sec", "else": "big"},
            {"id": "sec", "kind": "approval", "role": "admin", "label": "Security review", "next": "big"},
            {"id": "big", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": "50000.00"}, "then": "fin", "else": "end"},
            {"id": "fin", "kind": "approval", "role": "finance", "next": "huge"},
            {"id": "huge", "kind": "condition",
             "when": {"field": "amount", "op": ">", "value": "500000.00"}, "then": "adm", "else": "end"},
            {"id": "adm", "kind": "approval", "role": "admin", "next": "end"},
        ],
    }


def test_a_workflow_can_route_on_an_answer(client, world):
    software = _make_type(client, world)
    saved = _save(client, _security_review_workflow())
    assert saved.status_code == 201 and saved.json()["problems"] == [], saved.text
    assert _publish(client, saved.json()["version_id"]).status_code == 200

    labels = {}
    for answer in ("Public", "Personal data"):
        login(client, world.requester)
        created = client.post("/requests", json=_request_body(
            world, request_type_id=software["id"], custom_values={"seats": "5", "data_class": answer}))
        assert created.status_code == 201, created.text
        assert client.post(f"/requests/{created.json()['id']}/submit").status_code == 200
        sent = _complete_and_send(client, world, client.get(f"/requests/{created.json()['id']}").json())
        labels[answer] = [s["step_label"] for s in sent["current_steps"]]
    assert len(labels["Public"]) == 1                                   # ₹40,000: the manager only
    assert labels["Personal data"][1] == "Security review" and len(labels["Personal data"]) == 2
