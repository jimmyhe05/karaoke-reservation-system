import json
import pytest
from datetime import datetime

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
    base = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 3,
        "contact_name": "Tester",
        "contact_phone": "555-0101",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
    }
    base.update(overrides)
    return base


def test_create_requires_admin(client):
    resp = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload()),
        content_type='application/json',
    )
    assert resp.status_code == 401


def test_create_accepts_json_from_frontend(client):
    login_admin(client)
    resp = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload(contact_name='Frontend JSON')),
        content_type='application/json',
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body['reservation']['contact_name'] == 'Frontend JSON'


def test_create_list_get_success(client):
    login_admin(client)
    create = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload()),
        content_type='application/json',
    )
    assert create.status_code == 201
    created = create.get_json()['reservation']

    listing = client.get(f"/api/reservations?date={created['date']}")
    assert listing.status_code == 200
    reservations = listing.get_json()['reservations']
    assert any(r['id'] == created['id'] for r in reservations)

    detail = client.get(f"/api/reservations/{created['id']}")
    assert detail.status_code == 200
    detail_body = detail.get_json()['reservation']
    assert detail_body['id'] == created['id']


def test_create_preserves_notes_and_total_cost_includes_tax(client):
    login_admin(client)
    create = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload(notes='Birthday setup')),
        content_type='application/json',
    )

    assert create.status_code == 201
    created = create.get_json()['reservation']
    assert created['notes'] == 'Birthday setup'
    assert created['total_cost'] == pytest.approx(36.93)


def test_conflict_returns_409(client):
    login_admin(client)
    today = datetime.now().strftime('%Y-%m-%d')
    payload = sample_payload(date=today, start_time="14:00", end_time="15:00")
    first = client.post(
        '/api/reservations',
        data=json.dumps(payload),
        content_type='application/json',
    )
    assert first.status_code == 201

    overlap = sample_payload(date=today, start_time="14:30", end_time="15:30")
    conflict = client.post(
        '/api/reservations',
        data=json.dumps(overlap),
        content_type='application/json',
    )
    assert conflict.status_code == 409
    body = conflict.get_json()
    assert body.get('error')
    assert body['error'].get('code') == 'conflict'


def test_validation_error_shape(client):
    login_admin(client)
    bad = sample_payload()
    bad.pop('date')
    resp = client.post(
        '/api/reservations',
        data=json.dumps(bad),
        content_type='application/json',
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['error']['code'] == 'validation_error'
    assert 'fields' in body['error']


def test_patch_updates_timeslot(client):
    login_admin(client)
    created = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload(start_time="16:00", end_time="17:00")),
        content_type='application/json',
    )
    reservation_id = created.get_json()['reservation']['id']

    patch_body = {"start_time": "17:00", "end_time": "18:00"}
    patched = client.patch(
        f"/api/reservations/{reservation_id}",
        data=json.dumps(patch_body),
        content_type='application/json',
    )
    assert patched.status_code == 200
    patched_res = patched.get_json()['reservation']
    assert patched_res['start_time'] == "17:00"
    assert patched_res['end_time'] == "18:00"


def test_delete_reservation(client):
    login_admin(client)
    created = client.post(
        '/api/reservations',
        data=json.dumps(sample_payload(start_time="18:00", end_time="19:00")),
        content_type='application/json',
    )
    reservation_id = created.get_json()['reservation']['id']

    deleted = client.delete(f"/api/reservations/{reservation_id}")
    assert deleted.status_code == 200

    missing = client.get(f"/api/reservations/{reservation_id}")
    assert missing.status_code == 404
