"""Login, sessions and tenancy (BUILD_PLAN §9; §11 M1: login works, wrong password fails, org A cannot read org B)."""

from tests.conftest import TEST_PASSWORD, login


def test_login_sets_a_session_cookie_and_me_returns_the_user(client, factory):
    org = factory.org()
    user = factory.user(org, "finance", limit="100000")

    response = client.post("/auth/login", json={"email": user.email.upper(), "password": TEST_PASSWORD})

    assert response.status_code == 200
    assert "orrfin_session" in response.cookies
    me = client.get("/auth/me").json()
    assert me["email"] == user.email and me["role"] == "finance"
    assert me["approval_limit"] == "100000.00"


def test_wrong_password_is_refused_without_a_cookie(client, factory):
    user = factory.user(factory.org(), "requester")

    response = client.post("/auth/login", json={"email": user.email, "password": "wrong-password"})

    assert response.status_code == 401
    assert "orrfin_session" not in response.cookies
    assert client.get("/auth/me").status_code == 401


def test_unknown_email_gets_the_same_message_as_a_wrong_password(client, factory):
    user = factory.user(factory.org(), "requester")

    unknown = client.post("/auth/login", json={"email": "nobody@test.orrfin.local", "password": "x"})
    wrong = client.post("/auth/login", json={"email": user.email, "password": "x"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_logout_ends_the_session(client, factory):
    login(client, factory.user(factory.org(), "buyer"))

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_business_routes_require_login(client):
    assert client.get("/categories").status_code == 401


def test_a_user_cannot_read_another_orgs_data(client, factory, db):
    from app.models import Category

    org_a, org_b = factory.org("Org A"), factory.org("Org B")
    category_b = Category(org_id=org_b.id, name="Org B secret category")
    db.add(category_b)
    db.commit()
    login(client, factory.user(org_a, "admin", limit="1"))

    single = client.get(f"/categories/{category_b.id}")
    listing = client.get("/categories")

    # 404, not 403: org A must not even learn that the row exists.
    assert single.status_code == 404
    assert all(c["id"] != str(category_b.id) for c in listing.json())
