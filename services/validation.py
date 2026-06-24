from datetime import datetime
from zoneinfo import ZoneInfo


def parse_time_safe(time_str):
    """Safely parse HH:MM strings, allowing 24-25 hour notation (e.g., "25:00").

    Returns a tuple of (datetime, is_extended) where is_extended indicates the
    time crossed midnight. Raises ValueError for malformed inputs or minutes
    outside 0-59, and hours above 25.
    """
    if ":" not in time_str:
        raise ValueError("Invalid time format; expected HH:MM")

    hours_part, minutes_part = time_str.split(":", 1)
    try:
        hours = int(hours_part)
        minutes = int(minutes_part)
    except Exception:
        raise ValueError("Invalid time format; expected HH:MM")

    if minutes < 0 or minutes > 59:
        raise ValueError("Minutes must be between 00 and 59")
    if hours < 0:
        raise ValueError("Hours must be non-negative")
    if hours > 25:
        raise ValueError("Hours must not exceed 25:00 (1 AM next day)")

    # Direct parse for same-day values
    if hours < 24:
        return datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M"), False

    # Extended notation (24-25)
    normalized_hour = hours % 24
    normalized_time_str = f"{normalized_hour:02d}:{minutes:02d}"
    return datetime.strptime(normalized_time_str, "%H:%M"), True


def time_to_minutes(time_str):
    """Convert HH:MM (optionally 24-25 hour) to minutes since 00:00 of the start day."""
    dt, is_extended = parse_time_safe(time_str)
    hours = int(time_str.split(":", 1)[0])
    minutes = dt.minute
    return hours * 60 + minutes


def normalize_time_range(date_str, start_str, end_str):
    """
    Normalize and validate a start/end time pair.
    Returns (normalized_start, normalized_end, start_minutes, end_minutes).
    normalized_end will use 24+ hour format when crossing midnight.
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Use YYYY-MM-DD.")

    start_dt, _ = parse_time_safe(start_str)
    end_dt, is_extended = parse_time_safe(end_str)

    normalized_start = start_dt.strftime("%H:%M")
    normalized_end = end_str

    start_minutes = time_to_minutes(normalized_start)

    if is_extended or end_dt <= start_dt:
        normalized_end = f"{end_dt.hour + 24:02d}:{end_dt.minute:02d}"
    else:
        normalized_end = end_dt.strftime("%H:%M")

    end_minutes = time_to_minutes(normalized_end)

    if start_minutes < 11 * 60 or end_minutes > 25 * 60 or end_minutes <= start_minutes:
        raise ValueError("Reservation must be between 11:00 and 01:00 next day, and end after start.")

    if date_obj < datetime.now(ZoneInfo("America/Chicago")).date():
        raise ValueError("Date cannot be in the past.")

    return normalized_start, normalized_end, start_minutes, end_minutes


def slots_overlap(start_a, end_a, start_b, end_b):
    """Return True when two half-open intervals (start, end) overlap."""
    return start_a < end_b and start_b < end_a


def find_conflict(conn, room_id, date, start_time_str, end_time_str, exclude_id=None):
    """Return the first conflicting reservation (excluding cancelled/idle/exclude_id) or None.

    - Considers half-open intervals [start, end) so back-to-back bookings are allowed.
    - Supports overnight times using 24-25h notation.
    - Ignores reservations placed into the idle area.
    - Deterministic ordering by start_time, id.
    """

    idle_ids = conn.execute("SELECT reservation_id FROM idle_reservations WHERE date = ?", (date,)).fetchall()
    idle_set = {row["reservation_id"] for row in idle_ids}

    existing = conn.execute(
        """
        SELECT id, start_time, end_time, status
        FROM reservations
        WHERE room_id = ? AND date = ? AND status NOT IN ('cancelled', 'pending', 'rejected')
        ORDER BY start_time, id
    """,
        (room_id, date),
    ).fetchall()

    new_start = time_to_minutes(start_time_str)
    new_end = time_to_minutes(end_time_str)

    for res in existing:
        if exclude_id and res["id"] == exclude_id:
            continue
        if res["id"] in idle_set:
            continue

        res_start = time_to_minutes(res["start_time"])
        res_end = time_to_minutes(res["end_time"])

        if slots_overlap(new_start, new_end, res_start, res_end):
            return res

    return None
