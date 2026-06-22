import sqlite3
import pytest

from app import (
    normalize_time_range,
    slots_overlap,
    compute_pricing,
    find_conflict,
)


FUTURE_DATE = "2099-01-01"


def make_conn_with_rooms(hourly_rate=35.0, peak_rate=50.0):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE rooms (
            id INTEGER PRIMARY KEY,
            name TEXT,
            capacity INTEGER,
            hourly_rate REAL,
            peak_hour_rate REAL
        );

        CREATE TABLE reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT DEFAULT 'confirmed'
        );

        CREATE TABLE idle_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_id INTEGER NOT NULL,
            date TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO rooms (id, name, capacity, hourly_rate, peak_hour_rate) VALUES (?, ?, ?, ?, ?)",
        (1, "Room 1", 8, hourly_rate, peak_rate),
    )
    conn.commit()
    return conn


def insert_reservation(conn, room_id, date, start, end, status="confirmed"):
    cur = conn.execute(
        """
        INSERT INTO reservations (room_id, date, start_time, end_time, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (room_id, date, start, end, status),
    )
    conn.commit()
    return cur.lastrowid


def test_normalize_time_range_daytime():
    start, end, start_m, end_m = normalize_time_range(FUTURE_DATE, "11:00", "13:30")
    assert start == "11:00"
    assert end == "13:30"
    assert start_m == 11 * 60
    assert end_m == 13 * 60 + 30


def test_normalize_time_range_overnight():
    start, end, _, end_m = normalize_time_range(FUTURE_DATE, "23:00", "01:00")
    assert start == "23:00"
    assert end == "25:00"  # stored as 24+ format when crossing midnight
    assert end_m == 25 * 60


def test_normalize_time_range_rejects_outside_hours():
    with pytest.raises(ValueError):
        normalize_time_range(FUTURE_DATE, "10:00", "12:00")


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ((0, 60), (60, 120), False),  # touching edges
        ((0, 60), (59, 120), True),  # overlap by one minute
        ((120, 180), (0, 90), False),
        ((120, 180), (150, 200), True),
    ],
)
def test_slots_overlap(a, b, expected):
    assert slots_overlap(a[0], a[1], b[0], b[1]) is expected


def test_compute_pricing_early_only():
    conn = make_conn_with_rooms(hourly_rate=35.0, peak_rate=50.0)
    pricing = compute_pricing(conn, 1, "11:00", "12:00")
    assert pricing["subtotal"] == pytest.approx(35.0)
    assert pricing["tax"] == pytest.approx(round(35.0 * 0.055, 2))
    conn.close()


def test_compute_pricing_cross_early_prime():
    conn = make_conn_with_rooms(hourly_rate=35.0, peak_rate=50.0)
    # 0.5h early (17:30-18:00) @35 = 17.5; 1.5h prime (18:00-19:30) @50 = 75 -> 92.5 subtotal
    pricing = compute_pricing(conn, 1, "17:30", "19:30")
    assert pricing["subtotal"] == pytest.approx(92.5)
    conn.close()


def test_compute_pricing_overnight_late_only():
    conn = make_conn_with_rooms(hourly_rate=35.0, peak_rate=50.0)
    pricing = compute_pricing(conn, 1, "23:00", "25:00")
    # 2 hours at late rate (peak)
    assert pricing["subtotal"] == pytest.approx(100.0)
    conn.close()


def test_find_conflict_detects_overlap():
    conn = make_conn_with_rooms()
    existing_id = insert_reservation(conn, 1, FUTURE_DATE, "12:00", "14:00")
    conflict = find_conflict(conn, 1, FUTURE_DATE, "12:30", "13:00")
    assert conflict is not None
    assert conflict["id"] == existing_id
    conn.close()


def test_find_conflict_ignores_idle_reservations():
    conn = make_conn_with_rooms()
    res_id = insert_reservation(conn, 1, FUTURE_DATE, "12:00", "14:00")
    conn.execute(
        "INSERT INTO idle_reservations (reservation_id, date) VALUES (?, ?)",
        (res_id, FUTURE_DATE),
    )
    conn.commit()

    conflict = find_conflict(conn, 1, FUTURE_DATE, "12:30", "13:00")
    assert conflict is None
    conn.close()
