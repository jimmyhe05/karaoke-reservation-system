from services.validation import time_to_minutes
from config import Config


def calculate_cost(conn, room_id, start_time_str, end_time_str, tax_rate=None):
    pricing = compute_pricing(conn, room_id, start_time_str, end_time_str, tax_rate)
    return pricing["total"]


def compute_pricing(conn, room_id, start_time_str, end_time_str, tax_rate=None):
    """
    Compute subtotal, tax, and total for a reservation using room rates.

    - Uses room.hourly_rate for 11:00-18:00 (Early Bird)
    - Uses room.peak_hour_rate for 18:00-25:00 (6 PM - 1 AM)
    - Supports minute-level durations and overnight via 24+ hour end times.
    Returns dict with subtotal, tax, total, and period_charges breakdown.
    """
    if tax_rate is None:
        tax_rate = Config.TAX_RATE

    room = conn.execute("SELECT hourly_rate, peak_hour_rate FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        raise ValueError("Invalid room id for pricing")

    start_minutes = time_to_minutes(start_time_str)
    end_minutes = time_to_minutes(end_time_str)

    if end_minutes <= start_minutes:
        raise ValueError("End time must be after start time for pricing")

    # Boundaries in minutes from midnight
    EARLY_END = 18 * 60  # 18:00
    EVENING_END = 25 * 60  # 01:00 next day (25:00)

    current = start_minutes
    subtotal = 0.0
    period_charges = []

    while current < end_minutes:
        if current < EARLY_END:
            rate = room["hourly_rate"]
            period_label = "Early Bird (11 AM - 6 PM)"
            period_end = min(end_minutes, EARLY_END)
        else:
            rate = room["peak_hour_rate"]
            period_label = "Evening / Late (6 PM - 1 AM)"
            period_end = min(end_minutes, EVENING_END)

        duration_hours = (period_end - current) / 60.0
        cost = rate * duration_hours
        subtotal += cost
        period_charges.append(
            {
                "time": period_label,
                "rate": rate,
                "duration": round(duration_hours, 2),
                "cost": round(cost, 2),
            }
        )

        current = period_end

    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)

    return {
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "total": total,
        "period_charges": period_charges,
    }
