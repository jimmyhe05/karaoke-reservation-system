from datetime import datetime


def parse_time_safe(time_str):
    """Safely parse time strings, including 24+ hour format (e.g., "25:00").
    Returns (datetime, is_extended)
    """
    try:
        return datetime.strptime(time_str, '%H:%M'), False
    except ValueError:
        if ':' in time_str:
            hours, minutes = time_str.split(':')
            if int(hours) >= 24:
                normalized_hour = int(hours) % 24
                normalized_time_str = f"{normalized_hour:02d}:{minutes}"
                return datetime.strptime(normalized_time_str, '%H:%M'), True
        raise


def time_to_minutes(time_str):
    """Convert HH:MM (optionally 24+ hour) to minutes since 00:00 of the start day."""
    try:
        base_parts = time_str.split(":")
        hours = int(base_parts[0])
        minutes = int(base_parts[1])
    except Exception:
        raise ValueError("Invalid time format; expected HH:MM")

    # ensure format is valid via parse
    _, _ = parse_time_safe(time_str)
    return hours * 60 + minutes


def normalize_time_range(date_str, start_str, end_str):
    """
    Normalize and validate a start/end time pair.
    Returns (normalized_start, normalized_end, start_minutes, end_minutes).
    normalized_end will use 24+ hour format when crossing midnight.
    """
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('Invalid date format. Use YYYY-MM-DD.')

    start_dt, _ = parse_time_safe(start_str)
    end_dt, is_extended = parse_time_safe(end_str)

    normalized_start = start_dt.strftime('%H:%M')
    normalized_end = end_str

    start_minutes = time_to_minutes(normalized_start)

    if is_extended or end_dt <= start_dt:
        normalized_end = f"{end_dt.hour + 24:02d}:{end_dt.minute:02d}"
    else:
        normalized_end = end_dt.strftime('%H:%M')

    end_minutes = time_to_minutes(normalized_end)

    if start_minutes < 11 * 60 or end_minutes > 25 * 60 or end_minutes <= start_minutes:
        raise ValueError(
            'Reservation must be between 11:00 and 01:00 next day, and end after start.'
        )

    if date_obj < datetime.now().date():
        raise ValueError('Date cannot be in the past.')

    return normalized_start, normalized_end, start_minutes, end_minutes


def slots_overlap(start_a, end_a, start_b, end_b):
    """Return True when two half-open intervals (start, end) overlap."""
    return start_a < end_b and start_b < end_a


def find_conflict(conn, room_id, date, start_time_str, end_time_str, exclude_id=None):
    """Return the first conflicting reservation (excluding cancelled/idle/exclude_id) or None."""
    idle_ids = conn.execute(
        'SELECT reservation_id FROM idle_reservations WHERE date = ?', (date,)
    ).fetchall()
    idle_set = {row['reservation_id'] for row in idle_ids}

    existing = conn.execute('''
        SELECT id, start_time, end_time, status
        FROM reservations
        WHERE room_id = ? AND date = ? AND status != 'cancelled'
    ''', (room_id, date)).fetchall()

    new_start = time_to_minutes(start_time_str)
    new_end = time_to_minutes(end_time_str)

    for res in existing:
        if exclude_id and res['id'] == exclude_id:
            continue
        if res['id'] in idle_set:
            continue

        res_start = time_to_minutes(res['start_time'])
        res_end = time_to_minutes(res['end_time'])

        if slots_overlap(new_start, new_end, res_start, res_end):
            return res

    return None
