from services.validation import time_to_minutes, slots_overlap


def is_blackout(windows, date_str, start_time_str, end_time_str, room_id):
    """Return (blocked: bool, matching_window: dict|None)."""
    if not windows:
        return False, None

    new_start = time_to_minutes(start_time_str)
    new_end = time_to_minutes(end_time_str)

    for win in windows:
        if win.get("date") != date_str:
            continue
        win_room = win.get("room_id")
        if win_room is not None and win_room != room_id:
            continue

        if win.get("start_time") and win.get("end_time"):
            try:
                win_start = time_to_minutes(win["start_time"])
                win_end = time_to_minutes(win["end_time"])
            except Exception:
                continue
            if slots_overlap(new_start, new_end, win_start, win_end):
                return True, win
        else:
            # full-day blackout for matched room/date
            return True, win

    return False, None
