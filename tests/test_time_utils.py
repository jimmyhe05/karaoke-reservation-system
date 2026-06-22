import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.validation import parse_time_safe, normalize_time_range, time_to_minutes
from app import app, init_db, compute_pricing, get_db


@pytest.fixture(autouse=True)
def app_context(tmp_path):
    app.config['DATABASE'] = str(tmp_path / 'test.db')
    app.config['TESTING'] = True
    with app.app_context():
        init_db()
    yield


def test_parse_time_allows_25_hour():
    dt, is_extended = parse_time_safe("25:00")
    assert is_extended is True
    assert dt.hour == 1 and dt.minute == 0
    assert time_to_minutes("25:00") == 1500


def test_parse_time_rejects_bad_formats():
    for bad in ["abc", "12:99", "26:01", "-1:00", "24:60", "25:61", "1234"]:
        with pytest.raises(ValueError):
            parse_time_safe(bad)


def test_normalize_time_range_over_midnight():
    today = datetime.now(ZoneInfo('America/Chicago')).strftime('%Y-%m-%d')
    start, end, start_min, end_min = normalize_time_range(today, "23:30", "01:00")
    assert start == "23:30"
    assert end == "25:00"
    assert start_min == 23 * 60 + 30
    assert end_min == 25 * 60


def test_normalize_time_range_rejects_before_open():
    today = datetime.now(ZoneInfo('America/Chicago')).strftime('%Y-%m-%d')
    with pytest.raises(ValueError):
        normalize_time_range(today, "10:00", "12:00")


def test_normalize_time_range_rejects_past_date():
    yesterday = (datetime.now(ZoneInfo('America/Chicago')) - timedelta(days=1)).strftime('%Y-%m-%d')
    with pytest.raises(ValueError):
        normalize_time_range(yesterday, "11:00", "12:00")


def test_compute_pricing_over_midnight():
    with app.app_context():
        conn = get_db()
        pricing = compute_pricing(conn, 1, "23:00", "25:00")
        assert pricing['subtotal'] > 0
        assert pricing['total'] >= pricing['subtotal']


def test_compute_pricing_invalid_room():
    with app.app_context():
        conn = get_db()
        with pytest.raises(ValueError):
            compute_pricing(conn, 999, "12:00", "13:00")
