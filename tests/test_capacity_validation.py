import json
from datetime import datetime

import pytest

from app import app, init_db


@pytest.fixture(autouse=True)
def app_context(tmp_path):
    app.config['DATABASE'] = str(tmp_path / 'test.db')
    app.config['TESTING'] = True
    app.config['ADMIN_USERNAME'] = 'admin'
    app.config['ADMIN_PASSWORD'] = 'admin'
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
    payload = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 9,
        "contact_name": "Capacity Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    payload.update(overrides)
    return payload


def test_rest_create_rejects_party_over_room_capacity(client):
    login_admin(client)
    response = client.post(
        "/api/reservations",
        data=json.dumps(sample_payload()),
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "validation_error"
    assert "capacity" in body["error"]["message"].lower()


def test_legacy_update_rejects_party_over_room_capacity(client):
    login_admin(client)
    create = client.post(
        "/reservation",
        data=json.dumps(sample_payload(num_people=2)),
        content_type="application/json",
    )
    assert create.status_code == 200

    reservation_id = client.get(
        f"/api/daily_reservations?date={sample_payload()['date']}"
    ).get_json()["rooms"][0]["reservations"][0]["id"]

    update = client.post(
        f"/update_reservation/{reservation_id}",
        data=json.dumps({"num_people": 9}),
        content_type="application/json",
    )

    assert update.status_code == 400
    assert "capacity" in update.get_json()["error"].lower()
