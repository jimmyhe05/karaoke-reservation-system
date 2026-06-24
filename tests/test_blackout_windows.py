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
    with app.app_context():
        init_db()
    yield


@pytest.fixture
def client():
    return app.test_client()


def login_admin(client):
    return client.post(
        "/login",
        data=json.dumps({"username": "admin", "password": "admin"}),
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


def test_full_day_blackout_blocks_creation(client):
    login_admin(client)
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    app.config["BLACKOUT_WINDOWS"] = [{"date": today, "room_id": 1}]

    resp = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload(date=today)),
        content_type="application/json",
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"]["code"] == "blackout"


def test_partial_blackout_blocks_overlap(client):
    login_admin(client)
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    app.config["BLACKOUT_WINDOWS"] = [{"date": today, "room_id": 1, "start_time": "12:30", "end_time": "14:00"}]

    resp = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload(date=today, start_time="12:00", end_time="13:00")),
        content_type="application/json",
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"]["code"] == "blackout"


def test_non_matching_room_allows_creation(client):
    login_admin(client)
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    app.config["BLACKOUT_WINDOWS"] = [{"date": today, "room_id": 2}]

    resp = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload(date=today, room_id=1)),
        content_type="application/json",
    )
    assert resp.status_code == 201


def test_move_respects_blackout(client):
    login_admin(client)
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    app.config["BLACKOUT_WINDOWS"] = [{"date": today, "room_id": 2}]

    created = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload(date=today, room_id=1, start_time="15:00", end_time="16:00")),
        content_type="application/json",
    )
    rid = created.get_json()["reservation"]["id"]

    move_payload = {
        "reservation_id": rid,
        "room_id": 2,
        "start_time": "15:00",
        "date": today,
    }
    move_resp = client.post(
        "/move_reservation",
        data=json.dumps(move_payload),
        content_type="application/json",
    )
    assert move_resp.status_code == 409
    body = move_resp.get_json()
    assert body["error"]["code"] == "blackout"
