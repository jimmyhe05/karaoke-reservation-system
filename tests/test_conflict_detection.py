import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import app, init_db, get_db
from services.validation import find_conflict


@pytest.fixture(autouse=True)
def app_context(tmp_path):
    app.config["DATABASE"] = str(tmp_path / "test.db")
    app.config["TESTING"] = True
    with app.app_context():
        init_db()
    yield


def make_reservation(conn, **kwargs):
    defaults = {
        "date": datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d"),
        "start_time": "12:00",
        "end_time": "13:00",
        "num_people": 2,
        "contact_name": "Tester",
        "contact_phone": "555",
        "contact_email": "",
        "room_id": 1,
        "language": "en",
        "status": "confirmed",
        "total_cost": 10.0,
        "notes": "",
    }
    defaults.update(kwargs)
    cur = conn.execute(
        """INSERT INTO reservations
           (date, start_time, end_time, num_people, contact_name, contact_phone,
            contact_email, room_id, language, status, total_cost, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["date"],
            defaults["start_time"],
            defaults["end_time"],
            defaults["num_people"],
            defaults["contact_name"],
            defaults["contact_phone"],
            defaults["contact_email"],
            defaults["room_id"],
            defaults["language"],
            defaults["status"],
            defaults["total_cost"],
            defaults["notes"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def test_overlap_detected():
    with app.app_context():
        conn = get_db()
        date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
        make_reservation(conn, date=date, start_time="12:00", end_time="13:00")
        conflict = find_conflict(conn, 1, date, "12:30", "13:30")
        assert conflict is not None


def test_back_to_back_allowed():
    with app.app_context():
        conn = get_db()
        date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
        make_reservation(conn, date=date, start_time="12:00", end_time="13:00")
        conflict = find_conflict(conn, 1, date, "13:00", "14:00")
        assert conflict is None


def test_idle_excluded_from_conflict():
    with app.app_context():
        conn = get_db()
        date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
        res_id = make_reservation(conn, date=date, start_time="14:00", end_time="15:00")
        conn.execute(
            "INSERT INTO idle_reservations (reservation_id, date) VALUES (?, ?)",
            (res_id, date),
        )
        conn.commit()
        conflict = find_conflict(conn, 1, date, "14:00", "15:00")
        assert conflict is None


def test_cancelled_excluded_from_conflict():
    with app.app_context():
        conn = get_db()
        date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
        make_reservation(
            conn, date=date, start_time="16:00", end_time="17:00", status="cancelled"
        )
        conflict = find_conflict(conn, 1, date, "16:00", "17:00")
        assert conflict is None


def test_overnight_conflict_detected():
    with app.app_context():
        conn = get_db()
        date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
        make_reservation(conn, date=date, start_time="23:30", end_time="25:00")
        conflict = find_conflict(conn, 1, date, "24:30", "25:30")
        assert conflict is not None
