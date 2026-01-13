import json
import pytest
from datetime import datetime
from app import app, init_db


@pytest.fixture(autouse=True)
def app_context(tmp_path):
    # Use a temp DB per test run
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
    return client.post("/login", data=json.dumps({
        "username": "admin",
        "password": "admin"
    }), content_type="application/json")


def test_requires_auth_for_mutations(client):
    payload = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    resp = client.post("/reservation", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 401


def test_create_reservation_success(client):
    login_admin(client)
    payload = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    resp = client.post("/reservation", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("message") == "Reservation created successfully"


def test_conflict_detection(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    base_payload = {
        "date": today,
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    # create first
    resp1 = client.post("/reservation", data=json.dumps(base_payload), content_type="application/json")
    assert resp1.status_code == 200

    # overlapping reservation should 409
    payload2 = base_payload.copy()
    payload2.update({"start_time": "12:30", "end_time": "13:30"})
    resp2 = client.post("/reservation", data=json.dumps(payload2), content_type="application/json")
    assert resp2.status_code == 409
    data2 = resp2.get_json()
    assert data2.get("error")


def test_move_to_idle_and_back(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    payload = {
        "date": today,
        "start_time": "14:00",
        "end_time": "15:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    create_resp = client.post("/reservation", data=json.dumps(payload), content_type="application/json")
    assert create_resp.status_code == 200

    # fetch the reservation id via daily reservations API
    daily = client.get(f"/api/daily_reservations?date={today}")
    assert daily.status_code == 200
    res_list = daily.get_json()["rooms"][0]["reservations"]
    assert res_list
    res_id = res_list[0]["id"]

    # move to idle
    idle_resp = client.post(f"/move_to_idle/{res_id}")
    assert idle_resp.status_code == 200

    # move from idle to room 2 at 15:00
    move_payload = {
        "reservation_id": res_id,
        "room_id": 2,
        "start_time": "15:00",
        "date": today,
    }
    move_resp = client.post("/move_reservation", data=json.dumps(move_payload), content_type="application/json")
    assert move_resp.status_code == 200
    moved = move_resp.get_json()["reservation"]
    assert moved["room_id"] == 2
    assert moved["start_time"] == "15:00"


def test_idle_persists_and_excludes_from_rooms(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    payload = {
        "date": today,
        "start_time": "13:00",
        "end_time": "14:00",
        "num_people": 2,
        "contact_name": "IdleTester",
        "contact_phone": "555-0102",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }

    # Create reservation and confirm it appears in room timeline
    create_resp = client.post("/reservation", data=json.dumps(payload), content_type="application/json")
    assert create_resp.status_code == 200

    daily_before = client.get(f"/api/daily_reservations?date={today}").get_json()
    res_list_before = daily_before["rooms"][0]["reservations"]
    assert len(res_list_before) == 1
    res_id = res_list_before[0]["id"]

    # Move to idle and verify it no longer appears in rooms but does in idle_reservations
    idle_resp = client.post(f"/move_to_idle/{res_id}")
    assert idle_resp.status_code == 200

    daily_after = client.get(f"/api/daily_reservations?date={today}").get_json()
    assert daily_after["rooms"][0]["reservations"] == []
    idle_list = daily_after.get("idle_reservations", [])
    assert len(idle_list) == 1
    assert idle_list[0]["id"] == res_id


def test_move_from_idle_clears_idle_and_places_in_room(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    payload = {
        "date": today,
        "start_time": "11:30",
        "end_time": "12:30",
        "num_people": 3,
        "contact_name": "Mover",
        "contact_phone": "555-0103",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }

    create_resp = client.post("/reservation", data=json.dumps(payload), content_type="application/json")
    assert create_resp.status_code == 200

    res_id = client.get(f"/api/daily_reservations?date={today}").get_json()["rooms"][0]["reservations"][0]["id"]

    # Move to idle
    assert client.post(f"/move_to_idle/{res_id}").status_code == 200

    # Move from idle to room 2 at 12:30
    move_payload = {
        "reservation_id": res_id,
        "room_id": 2,
        "start_time": "12:30",
        "date": today,
    }
    move_resp = client.post("/move_reservation", data=json.dumps(move_payload), content_type="application/json")
    assert move_resp.status_code == 200

    # After move: idle list empty, room 1 empty, room 2 has the reservation at 12:30
    daily_after = client.get(f"/api/daily_reservations?date={today}").get_json()
    assert daily_after.get("idle_reservations", []) == []
    assert daily_after["rooms"][0]["reservations"] == []  # room 1
    room2_res = daily_after["rooms"][1]["reservations"]
    assert len(room2_res) == 1
    assert room2_res[0]["id"] == res_id
    assert room2_res[0]["start_time"] == "12:30"


def test_public_schedule_is_anonymized(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    payload = {
        "date": today,
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    client.post("/reservation", data=json.dumps(payload), content_type="application/json")

    public_resp = client.get(f"/api/public_schedule?date={today}")
    assert public_resp.status_code == 200
    data = public_resp.get_json()
    assert 'rooms' in data
    first_room = data['rooms'][0]
    assert 'reservations' in first_room
    slot = first_room['reservations'][0]
    assert 'start_time' in slot and 'end_time' in slot
    assert 'status' in slot
    # No contact details should be present
    assert 'contact_name' not in slot


def test_login_me_logout_flow(client):
    # initially not admin
    me = client.get('/api/me').get_json()
    assert me['is_admin'] is False

    resp = login_admin(client)
    assert resp.status_code == 200

    me2 = client.get('/api/me').get_json()
    assert me2['is_admin'] is True

    logout_resp = client.post('/logout')
    assert logout_resp.status_code == 200

    me3 = client.get('/api/me').get_json()
    assert me3['is_admin'] is False
