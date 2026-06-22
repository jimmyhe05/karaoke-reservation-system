import json
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import app, init_db


@pytest.fixture(autouse=True)
def app_context(tmp_path):
    app.config["DATABASE"] = str(tmp_path / "test.db")
    app.config["TESTING"] = True
    app.config["ADMIN_USERNAME"] = "admin"
    app.config["ADMIN_PASSWORD"] = "admin"
    app.config["STAFF_USERNAME"] = "staff"
    app.config["STAFF_PASSWORD"] = "staff"
    with app.app_context():
        init_db()
    yield


@pytest.fixture
def client():
    return app.test_client()


def login(client, username, password):
    return client.post(
        "/login",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )


def sample_payload(**overrides):
    base = {
        "date": datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d"),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    base.update(overrides)
    return base


def test_staff_can_login_and_me_reflects_role(client):
    resp = login(client, "staff", "staff")
    assert resp.status_code == 200
    me = client.get("/api/me").get_json()
    assert me["role"] == "staff"
    assert me["is_admin"] is False
    assert me["can_manage_reservations"] is True


def test_admin_role_allows_mutation(client):
    login(client, "admin", "admin")
    create = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload()),
        content_type="application/json",
    )
    assert create.status_code == 201


def test_staff_can_create_edit_and_delete_reservations(client):
    login(client, "staff", "staff")
    create = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload()),
        content_type="application/json",
    )
    assert create.status_code == 201

    reservation_id = create.get_json()["reservation"]["id"]
    update = client.patch(
        f"/api/reservations/{reservation_id}",
        data=json.dumps({"notes": "Updated by staff"}),
        content_type="application/json",
    )
    assert update.status_code == 200
    assert update.get_json()["reservation"]["notes"] == "Updated by staff"

    delete = client.delete(f"/api/reservations/{reservation_id}")
    assert delete.status_code == 200


def test_home_page_is_not_auth_gated(client):
    assert client.get("/").status_code == 302
    login(client, "staff", "staff")
    assert client.get("/").status_code == 302


def test_invalid_credentials(client):
    resp = login(client, "nope", "nope")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"]["code"] == "invalid_credentials"
