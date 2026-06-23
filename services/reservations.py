from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging
import contextvars
import asyncio
from typing import List

from config import Config
from services.db import get_db, is_postgres_connection
from services.blackout import is_blackout as is_blackout_service
from services.validation import normalize_time_range, find_conflict, time_to_minutes
from services.pricing import calculate_cost

logger = logging.getLogger(__name__)

# Context variables to hold request metadata from FastAPI middleware
request_meta = contextvars.ContextVar("request_meta", default={})


# ---- SSE Real-Time Updates Broker ----
class SSEBroker:
    def __init__(self):
        self.listeners: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.listeners:
            self.listeners.remove(q)

    def publish(self, data: str):
        for q in self.listeners:
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(q.put_nowait, data)
            except RuntimeError:
                pass

sse_broker = SSEBroker()


# ---- Serialization helpers ----

def fetch_idle_set(conn, date=None):
    if date:
        rows = conn.execute(
            "SELECT reservation_id FROM idle_reservations WHERE date = ?", (date,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT reservation_id FROM idle_reservations").fetchall()
    return {row["reservation_id"] for row in rows}


def serialize_reservation_row(row, in_idle=False):
    if not row:
        return None
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "date": row["date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "num_people": row["num_people"],
        "contact_name": row["contact_name"],
        "contact_phone": row["contact_phone"],
        "contact_email": row["contact_email"],
        "language": row["language"],
        "notes": row["notes"],
        "status": row["status"],
        "total_cost": row["total_cost"],
        "in_idle": bool(in_idle),
    }


# ---- Helpers ----

def _blackout_windows():
    windows = getattr(Config, "BLACKOUT_WINDOWS", [])
    return windows if isinstance(windows, list) else []


def is_blackout(date_str, start_time_str, end_time_str, room_id):
    windows = _blackout_windows()
    return is_blackout_service(windows, date_str, start_time_str, end_time_str, room_id)


def validate_room_capacity(conn, room_id, num_people):
    room = conn.execute(
        "SELECT capacity FROM rooms WHERE id = ?", (room_id,)
    ).fetchone()
    if not room:
        return False, f"Invalid room id {room_id}", room
    if num_people <= 0:
        return False, "Number of people must be 1 or more", room
    if num_people > room["capacity"]:
        return False, f"Room capacity is {room['capacity']} people", room
    return True, None, room


def log_action(action: str, **details):
    meta = request_meta.get()
    metadata = {
        "action": action,
        "path": meta.get("path", ""),
        "method": meta.get("method", ""),
        "request_id": meta.get("request_id", ""),
        "role": meta.get("role", "guest"),
    }
    metadata.update(details)
    logger.info(metadata)

    # Persist to audit_log (best-effort)
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO audit_log (action, role, path, method, request_id, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                metadata.get("action"),
                metadata.get("role"),
                metadata.get("path"),
                metadata.get("method"),
                metadata.get("request_id"),
                json.dumps(details or {}),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning({"action": "audit_log.failed", "error": str(exc)})
    finally:
        conn.close()


def record_reservation_history(conn, reservation_id: int, action: str, snapshot: dict):
    try:
        conn.execute(
            """INSERT INTO reservation_history (reservation_id, action, snapshot)
               VALUES (?, ?, ?)""",
            (reservation_id, action, json.dumps(snapshot)),
        )
        conn.commit()
    except Exception as exc:
        logger.warning(
            {"action": "reservation_history.failed", "error": str(exc)}
        )


# ---- API payload helpers ----

def create_reservation_api_payload(
    data,
    api_error,
    api_ok,
    *,
    success_message: str = "Reservation created",
    status_code: int = 201,
    include_success: bool = False,
):
    if not data:
        return api_error("No data provided", 400, code="no_payload")

    required_fields = [
        "date",
        "start_time",
        "end_time",
        "num_people",
        "contact_name",
        "contact_phone",
        "room_id",
    ]
    missing = [f for f in required_fields if data.get(f) in (None, "", [])]
    if missing:
        return api_error(
            "Missing required fields", 400, code="validation_error", fields=missing
        )

    try:
        room_id = int(data.get("room_id"))
    except Exception:
        return api_error(
            "Invalid room id", 400, code="validation_error", fields=["room_id"]
        )

    idle_selected = str(data.get("idle", "")).lower() in ("true", "1", "yes")

    try:
        num_people = int(data.get("num_people"))
    except Exception:
        return api_error(
            "Invalid number of people",
            400,
            code="validation_error",
            fields=["num_people"],
        )

    try:
        normalized_start, normalized_end, _, _ = normalize_time_range(
            data.get("date"), data.get("start_time"), data.get("end_time")
        )
    except ValueError as e:
        return api_error(
            str(e),
            400,
            code="validation_error",
            fields=["date", "start_time", "end_time"],
        )

    conn = get_db()
    try:
        # CONCURRENCY LOCK
        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (room_id,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        ok, msg, room = validate_room_capacity(conn, room_id, num_people)
        if not ok:
            return api_error(
                msg, 400, code="validation_error", fields=["room_id", "num_people"]
            )

        blocked, win = is_blackout(
            data.get("date"), normalized_start, normalized_end, room_id
        )
        if blocked:
            return api_error(
                "Requested time is unavailable (maintenance/blackout)",
                409,
                code="blackout",
                fields=["start_time", "end_time", "room_id"],
                details={"blackout": win},
            )

        if not idle_selected:
            conflict = find_conflict(
                conn, room_id, data.get("date"), normalized_start, normalized_end
            )
            if conflict:
                return api_error(
                    "Room is not available for the selected time",
                    409,
                    code="conflict",
                    fields=["room_id", "start_time", "end_time"],
                    details={"conflict_with": conflict["id"]},
                )

        total_cost = calculate_cost(
            conn, room_id, normalized_start, normalized_end, getattr(Config, "TAX_RATE", 0.055)
        )

        status = data.get("status", "confirmed")
        insert_sql = """INSERT INTO reservations
           (date, start_time, end_time, num_people,
            contact_name, contact_phone, contact_email, room_id,
            total_cost, language, notes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        insert_params = (
            data.get("date"),
            normalized_start,
            normalized_end,
            num_people,
            data.get("contact_name"),
            data.get("contact_phone"),
            data.get("contact_email", ""),
            room_id,
            total_cost,
            data.get("language", "en"),
            data.get("notes", ""),
            status,
        )
        if is_postgres_connection(conn):
            cursor = conn.execute(insert_sql.replace("?", "%s") + " RETURNING id", insert_params)
            reservation_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(insert_sql, insert_params)
            reservation_id = cursor.lastrowid

        if idle_selected:
            conn.execute(
                """INSERT INTO idle_reservations (reservation_id, date)
                   VALUES (?, ?)""",
                (reservation_id, data.get("date")),
            )

        conn.commit()

        new_row = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        record_reservation_history(
            conn,
            reservation_id,
            "created",
            serialize_reservation_row(new_row, in_idle=idle_selected),
        )
        log_action(
            "reservation.create.api",
            reservation_id=reservation_id,
            room_id=room_id,
            date=data.get("date"),
            start_time=normalized_start,
            end_time=normalized_end,
            num_people=num_people,
        )
        
        # Publish change for SSE subscribers
        sse_broker.publish("refresh")
        
        payload = {"reservation": serialize_reservation_row(new_row, in_idle=idle_selected)}
        if include_success:
            payload["success"] = True
        return api_ok(payload, message=success_message, status=status_code)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def update_reservation_api_payload(reservation_id, data, api_error, api_ok):
    if not data:
        return api_error("No data provided", 400, code="no_payload")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        if not existing:
            return api_error("Reservation not found", 404, code="not_found")

        try:
            room_id = int(data.get("room_id", existing["room_id"]))
        except Exception:
            return api_error(
                "Invalid room id", 400, code="validation_error", fields=["room_id"]
            )

        # CONCURRENCY LOCK
        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (room_id,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch existing inside the locked transaction just in case
        existing = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        if not existing:
            return api_error("Reservation not found", 404, code="not_found")

        date = data.get("date", existing["date"])
        start_time_raw = data.get("start_time", existing["start_time"])
        end_time_raw = data.get("end_time", existing["end_time"])

        try:
            normalized_start, normalized_end, _, _ = normalize_time_range(
                date, start_time_raw, end_time_raw
            )
        except ValueError as e:
            return api_error(
                str(e),
                400,
                code="validation_error",
                fields=["start_time", "end_time", "date"],
            )

        blocked, win = is_blackout(date, normalized_start, normalized_end, room_id)
        if blocked:
            return api_error(
                "Requested time is unavailable (maintenance/blackout)",
                409,
                code="blackout",
                fields=["start_time", "end_time", "room_id"],
                details={"blackout": win},
            )

        conflict = find_conflict(
            conn, room_id, date, normalized_start, normalized_end, exclude_id=reservation_id
        )
        if conflict:
            return api_error(
                "The selected time slot is already occupied by another reservation",
                409,
                code="conflict",
                fields=["start_time", "end_time"],
            )

        try:
            num_people = int(data.get("num_people", existing["num_people"]))
        except Exception:
            return api_error(
                "Invalid number of people",
                400,
                code="validation_error",
                fields=["num_people"],
            )

        ok, msg, room = validate_room_capacity(conn, room_id, num_people)
        if not ok:
            return api_error(
                msg, 400, code="validation_error", fields=["room_id", "num_people"]
            )

        time_or_room_changed = (
            normalized_start != existing["start_time"]
            or normalized_end != existing["end_time"]
            or room_id != existing["room_id"]
        )

        if time_or_room_changed:
            total_cost = calculate_cost(
                conn,
                room_id,
                normalized_start,
                normalized_end,
                getattr(Config, "TAX_RATE", 0.055),
            )
        else:
            total_cost = existing["total_cost"]

        contact_name = data.get("contact_name", existing["contact_name"])
        contact_phone = data.get("contact_phone", existing["contact_phone"])
        contact_email = data.get("contact_email", existing["contact_email"])
        language = data.get("language", existing["language"])
        notes = data.get("notes", existing["notes"])
        status = data.get("status", existing["status"])

        conn.execute(
            """UPDATE reservations
               SET room_id = ?, date = ?, start_time = ?, end_time = ?,
                   contact_name = ?, contact_phone = ?, contact_email = ?,
                   num_people = ?, language = ?, notes = ?, status = ?, total_cost = ?
               WHERE id = ?""",
            (
                room_id,
                date,
                normalized_start,
                normalized_end,
                contact_name,
                contact_phone,
                contact_email,
                num_people,
                language,
                notes,
                status,
                total_cost,
                reservation_id,
            ),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        record_reservation_history(
            conn,
            reservation_id,
            "updated",
            serialize_reservation_row(updated),
        )
        log_action(
            "reservation.update.api",
            reservation_id=reservation_id,
            room_id=room_id,
            date=date,
            start_time=normalized_start,
            end_time=normalized_end,
            num_people=num_people,
            status=status,
        )
        
        # Publish change for SSE subscribers
        sse_broker.publish("refresh")
        
        return api_ok(
            {"reservation": serialize_reservation_row(updated)},
            message="Reservation updated",
        )
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def delete_reservation_api_payload(reservation_id, api_error, api_ok):
    conn = get_db()
    try:
        reservation = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        if not reservation:
            return api_error("Reservation not found", 404, code="not_found")

        # CONCURRENCY LOCK
        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (reservation["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        conn.execute(
            "DELETE FROM reservation_history WHERE reservation_id = ?", (reservation_id,)
        )
        conn.execute(
            "DELETE FROM idle_reservations WHERE reservation_id = ?", (reservation_id,)
        )
        conn.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
        conn.commit()

        log_action(
            "reservation.delete.api",
            reservation_id=reservation_id,
            room_id=reservation["room_id"],
            date=reservation["date"],
        )
        
        # Publish change for SSE subscribers
        sse_broker.publish("refresh")
        
        return api_ok({"id": reservation_id}, message="Reservation deleted", status=200)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ---- Misc helpers ----

def get_today_stats(conn, today=None):
    if today is None:
        today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")

    total_reservations = conn.execute(
        """
        SELECT COUNT(*) as count
        FROM reservations
        WHERE date = ?
    """,
        (today,),
    ).fetchone()["count"]

    total_rooms = conn.execute(
        "SELECT COUNT(*) as count FROM rooms WHERE id > 0"
    ).fetchone()["count"]
    total_hours = 14  # 11 AM to 1 AM = 14 hours
    total_room_hours = total_rooms * total_hours

    reservations = conn.execute(
        """SELECT start_time, end_time
           FROM reservations
           WHERE date = ? AND status != 'cancelled' """,
        (today,),
    ).fetchall()
    occupied_hours = sum(
        (time_to_minutes(row["end_time"]) - time_to_minutes(row["start_time"])) / 60
        for row in reservations
    )

    occupancy_rate = round((occupied_hours / total_room_hours) * 100, 1)

    return {"total_reservations": total_reservations, "occupancy_rate": occupancy_rate}


def create_pending_request_api(data, user_id, api_error, api_ok):
    """Create a reservation with status 'pending' (bypassing conflicts) and send email alerts."""
    if not data:
        return api_error("No data provided", 400, code="no_payload")

    required_fields = [
        "date",
        "start_time",
        "end_time",
        "num_people",
        "contact_name",
        "contact_phone",
        "room_id",
    ]
    missing = [f for f in required_fields if data.get(f) in (None, "", [])]
    if missing:
        return api_error(
            "Missing required fields", 400, code="validation_error", fields=missing
        )

    try:
        room_id = int(data.get("room_id"))
    except Exception:
        return api_error(
            "Invalid room id", 400, code="validation_error", fields=["room_id"]
        )

    try:
        num_people = int(data.get("num_people"))
    except Exception:
        return api_error(
            "Invalid number of people",
            400,
            code="validation_error",
            fields=["num_people"],
        )

    try:
        normalized_start, normalized_end, _, _ = normalize_time_range(
            data.get("date"), data.get("start_time"), data.get("end_time")
        )
    except ValueError as e:
        return api_error(
            str(e),
            400,
            code="validation_error",
            fields=["date", "start_time", "end_time"],
        )

    conn = get_db()
    try:
        # CONCURRENCY LOCK
        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (room_id,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        ok, msg, room = validate_room_capacity(conn, room_id, num_people)
        if not ok:
            return api_error(
                msg, 400, code="validation_error", fields=["room_id", "num_people"]
            )

        blocked, win = is_blackout(
            data.get("date"), normalized_start, normalized_end, room_id
        )
        if blocked:
            return api_error(
                "Requested time is unavailable (maintenance/blackout)",
                409,
                code="blackout",
                fields=["start_time", "end_time", "room_id"],
                details={"blackout": win},
            )

        total_cost = calculate_cost(
            conn, room_id, normalized_start, normalized_end, getattr(Config, "TAX_RATE", 0.055)
        )

        insert_sql = """INSERT INTO reservations
           (date, start_time, end_time, num_people,
            contact_name, contact_phone, contact_email, room_id,
            total_cost, language, notes, status, user_id, requested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)"""

        requested_at = datetime.utcnow()
        insert_params = (
            data.get("date"),
            normalized_start,
            normalized_end,
            num_people,
            data.get("contact_name"),
            data.get("contact_phone"),
            data.get("contact_email", ""),
            room_id,
            total_cost,
            data.get("language", "en"),
            data.get("notes", ""),
            user_id,
            requested_at
        )
        
        if is_postgres_connection(conn):
            cursor = conn.execute(insert_sql.replace("?", "%s") + " RETURNING id", insert_params)
            reservation_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(insert_sql, params=insert_params)
            reservation_id = cursor.lastrowid

        conn.commit()

        new_row = conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
        res_dict = dict(new_row)
        
        record_reservation_history(
            conn,
            reservation_id,
            "request_submitted",
            serialize_reservation_row(new_row, in_idle=False),
        )
        log_action(
            "reservation.request.api",
            reservation_id=reservation_id,
            description=f"Created pending request {reservation_id}"
        )
        
        # Publish change for SSE subscribers
        sse_broker.publish("refresh")
        
        # NOTE: Email calls (send_request_received, send_staff_notification) are triggered 
        # asynchronously inside background tasks at the router level.
        
        return api_ok(
            {"reservation": serialize_reservation_row(new_row, False)},
            message="Reservation request submitted",
            status=201
        )
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
