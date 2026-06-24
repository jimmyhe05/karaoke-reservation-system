import json
import uuid
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sse_starlette.sse import EventSourceResponse

from config import Config
from services.db import get_db, is_postgres_connection
from services.validation import parse_time_safe, normalize_time_range, find_conflict
from services.pricing import compute_pricing
from services.reservations import (
    fetch_idle_set,
    serialize_reservation_row,
    create_reservation_api_payload,
    update_reservation_api_payload,
    delete_reservation_api_payload,
    create_pending_request_api,
    record_reservation_history,
    log_action,
    sse_broker,
    is_blackout,
    publish_sse_event,
)
import services.auth as auth_service
import services.oauth as oauth_service
import services.email as email_service

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["config"] = Config


@pass_context
def custom_url_for(context: dict, name: str, /, **path_params):
    request = context["request"]
    if name == "static":
        if "filename" in path_params:
            path_params["path"] = path_params.pop("filename")
        query_params = {k: v for k, v in path_params.items() if k != "path"}
        path_params = {k: v for k, v in path_params.items() if k == "path"}
        url = request.url_for(name, **path_params)
        if query_params:
            url = url.include_query_params(**query_params)
        return url
    return request.url_for(name, **path_params)


templates.env.globals["url_for"] = custom_url_for


# ---- Response helpers ----


def serialize_dates(obj):
    from datetime import date, time

    if isinstance(obj, dict):
        return {k: serialize_dates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_dates(x) for x in obj]
    elif isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    return obj


def api_error(message: str, status_code: int = 400, code=None, fields=None, details=None, status: int = None):
    final_status = status if status is not None else status_code
    payload = {"error": {"message": message}}
    if code:
        payload["error"]["code"] = code
    if fields:
        payload["error"]["fields"] = fields
    if details:
        payload["error"]["details"] = details
    return JSONResponse(content=serialize_dates(payload), status_code=final_status)


def api_ok(data=None, message=None, status_code: int = 200, status: int = None):
    final_status = status if status is not None else status_code
    payload = {}
    if message:
        payload["message"] = message
    if data is not None:
        payload.update(data)
    return JSONResponse(content=serialize_dates(payload), status_code=final_status)


async def get_request_payload(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        pass
    try:
        form = await request.form()
        if form:
            return dict(form)
    except Exception:
        pass
    return {}


# ---- Auth Helper Dependencies ----


def check_worker(request: Request):
    role = request.session.get("role", "guest")
    if role not in {"admin", "staff"}:
        if role == "guest":
            return api_error("Worker login required", 401, code="auth_required")
        return api_error("Forbidden", 403, code="forbidden")
    return None


# ---- Endpoints ----


@router.get("/api/daily_reservations")
def api_daily_reservations(request: Request, date: str = None):
    if not date:
        return api_error("Date parameter is required", 400, code="validation_error", fields=["date"])

    conn = get_db()
    try:
        rooms = conn.execute("SELECT * FROM rooms WHERE id > 0 ORDER BY id").fetchall()

        role = request.session.get("role", "guest")
        user_id = request.session.get("user_id")
        is_worker = role in ("admin", "staff")

        # Get idle reservations for this date
        idle_set = fetch_idle_set(conn, date)

        result = {"date": date, "rooms": [], "idle_reservations": []}

        for room in rooms:
            reservations = conn.execute(
                """
                SELECT * FROM reservations
                WHERE room_id = ? AND date = ? AND status NOT IN ('cancelled', 'rejected')
                ORDER BY start_time
                """,
                (room["id"], date),
            ).fetchall()

            room_res = []
            for res in reservations:
                if res["id"] in idle_set:
                    continue
                serialized = serialize_reservation_row(res, False)
                if not is_worker:
                    is_owner = user_id is not None and res["user_id"] == user_id
                    if not is_owner:
                        serialized["contact_name"] = "Reserved"
                        serialized["contact_phone"] = "Masked"
                        serialized["contact_email"] = "Masked"
                        serialized["notes"] = ""
                room_res.append(serialized)
            result["rooms"].append(
                {
                    "id": room["id"],
                    "name": room["name"],
                    "reservations": room_res,
                }
            )

        # Build idle reservations payload
        if idle_set:
            placeholders = ",".join(["?"] * len(idle_set))
            idle_rows = conn.execute(
                f"""
                SELECT * FROM reservations
                WHERE id IN ({placeholders}) AND date = ? AND status NOT IN ('cancelled', 'rejected')
                ORDER BY start_time
                """,
                list(idle_set) + [date],
            ).fetchall()

            idle_res_list = []
            for r in idle_rows:
                serialized = serialize_reservation_row(r, True)
                if not is_worker:
                    is_owner = user_id is not None and r["user_id"] == user_id
                    if not is_owner:
                        serialized["contact_name"] = "Reserved"
                        serialized["contact_phone"] = "Masked"
                        serialized["contact_email"] = "Masked"
                        serialized["notes"] = ""
                idle_res_list.append(serialized)
            result["idle_reservations"] = idle_res_list

        return api_ok(result)
    finally:
        conn.close()


@router.get("/api/reservations")
def api_list_reservations(request: Request, date: str = None, room_id: str = None, status: str = None):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    room_filter = None
    if room_id is not None:
        try:
            room_filter = int(room_id)
        except Exception:
            return api_error("Invalid room id", 400, code="validation_error", fields=["room_id"])

    conn = get_db()
    try:
        params = []
        query = "SELECT * FROM reservations WHERE 1=1"
        if date:
            query += " AND date = ?"
            params.append(date)
        if room_filter is not None:
            query += " AND room_id = ?"
            params.append(room_filter)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY date, room_id, start_time"

        rows = conn.execute(query, params).fetchall()
        idle_set = fetch_idle_set(conn, date if date else None)
        reservations = [serialize_reservation_row(r, r["id"] in idle_set) for r in rows]
        return api_ok({"reservations": reservations})
    finally:
        conn.close()


@router.get("/api/reservations/{reservation_id}")
def api_get_reservation(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row:
            return api_error("Reservation not found", 404, code="not_found")
        idle_set = fetch_idle_set(conn)
        return api_ok({"reservation": serialize_reservation_row(row, row["id"] in idle_set)})
    finally:
        conn.close()


@router.post("/api/reservations")
async def api_create_reservation(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    payload = await get_request_payload(request)
    return create_reservation_api_payload(payload, api_error, api_ok)


@router.patch("/api/reservations/{reservation_id}")
async def api_update_reservation_route(request: Request, reservation_id: int):
    role = request.session.get("role", "guest")
    user_id = request.session.get("user_id")

    is_worker = role in {"admin", "staff"}

    if not is_worker:
        if role != "customer" or user_id is None:
            return api_error("Worker login required", 401, code="auth_required")

        # Check ownership
        conn = get_db()
        try:
            existing = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
            if not existing:
                return api_error("Reservation not found", 404, code="not_found")
            if existing["user_id"] != user_id:
                return api_error("Forbidden", 403, code="forbidden")

            # Since they own it, we must validate restricted fields if any of them are in the request payload
            payload = await get_request_payload(request)
            restricted_fields = [
                "date",
                "room_id",
                "start_time",
                "end_time",
                "status",
                "total_cost",
                "deposit_paid",
                "user_id",
            ]
            for field in restricted_fields:
                if field in payload:
                    val = payload[field]
                    exist_val = existing[field]
                    if field in ["room_id", "user_id"]:
                        try:
                            val_int = int(val) if val is not None else None
                            exist_int = int(exist_val) if exist_val is not None else None
                            if val_int != exist_int:
                                return api_error(
                                    f"Cannot modify restricted field: {field}",
                                    400,
                                    code="validation_error",
                                    fields=[field],
                                )
                        except ValueError:
                            return api_error(f"Invalid {field} value", 400, code="validation_error", fields=[field])
                    elif field in ["total_cost", "deposit_paid"]:
                        try:
                            val_float = float(val) if val is not None else None
                            exist_float = float(exist_val) if exist_val is not None else 0.0
                            if val_float != exist_float:
                                return api_error(
                                    f"Cannot modify restricted field: {field}",
                                    400,
                                    code="validation_error",
                                    fields=[field],
                                )
                        except ValueError:
                            return api_error(f"Invalid {field} value", 400, code="validation_error", fields=[field])
                    else:
                        if field in ["start_time", "end_time"]:
                            try:
                                val_norm = val.strip() if isinstance(val, str) else val
                                exist_norm = exist_val.strip() if isinstance(exist_val, str) else exist_val
                                if ":" in str(val_norm) and ":" in str(exist_norm):
                                    val_parts = val_norm.split(":")[:2]
                                    exist_parts = exist_norm.split(":")[:2]
                                    if val_parts != exist_parts:
                                        return api_error(
                                            f"Cannot modify restricted field: {field}",
                                            400,
                                            code="validation_error",
                                            fields=[field],
                                        )
                                else:
                                    if val_norm != exist_norm:
                                        return api_error(
                                            f"Cannot modify restricted field: {field}",
                                            400,
                                            code="validation_error",
                                            fields=[field],
                                        )
                            except Exception:
                                if val != exist_val:
                                    return api_error(
                                        f"Cannot modify restricted field: {field}",
                                        400,
                                        code="validation_error",
                                        fields=[field],
                                    )
                        else:
                            if val != exist_val:
                                return api_error(
                                    f"Cannot modify restricted field: {field}",
                                    400,
                                    code="validation_error",
                                    fields=[field],
                                )
        finally:
            conn.close()
    else:
        payload = await get_request_payload(request)

    return update_reservation_api_payload(reservation_id, payload, api_error, api_ok)


@router.delete("/api/reservations/{reservation_id}")
def api_delete_reservation_route(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    return delete_reservation_api_payload(reservation_id, api_error, api_ok)


@router.get("/api/public_schedule")
def public_schedule(request: Request, date: str = None):
    if not date:
        return JSONResponse(status_code=400, content={"error": "Date parameter is required"})

    conn = get_db()
    try:
        rooms = conn.execute("SELECT * FROM rooms WHERE id > 0 ORDER BY id").fetchall()
        reservations = conn.execute("SELECT * FROM reservations WHERE date = ? ORDER BY start_time", (date,)).fetchall()
        idle_set = fetch_idle_set(conn, date)

        schedule = []
        for room in rooms:
            room_slots = []
            for res in reservations:
                if res["room_id"] != room["id"] or res["id"] in idle_set:
                    continue
                room_slots.append(
                    {
                        "start_time": res["start_time"],
                        "end_time": res["end_time"],
                        "status": res["status"],
                    }
                )
            schedule.append(
                {
                    "room_id": room["id"],
                    "room_name": room["name"],
                    "reservations": room_slots,
                }
            )

        return JSONResponse(content={"date": date, "rooms": schedule})
    finally:
        conn.close()


@router.get("/api/room_availability")
def check_room_availability(request: Request, date: str = None):
    if not date:
        return JSONResponse(status_code=400, content={"error": "Date parameter is required"})

    try:
        datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid date format"})

    conn = get_db()
    try:
        rooms = conn.execute("SELECT id FROM rooms WHERE id > 0").fetchall()
        room_ids = [room["id"] for room in rooms]

        booked_rooms = conn.execute(
            """
            SELECT DISTINCT r.room_id
            FROM reservations r
            WHERE r.date = ?
              AND r.status != 'cancelled'
              AND NOT EXISTS (
                SELECT 1 FROM idle_reservations i
                WHERE i.reservation_id = r.id AND i.date = r.date
              )
            """,
            (date,),
        ).fetchall()
        booked_room_ids = [room["room_id"] for room in booked_rooms]

        available_rooms = list(set(room_ids) - set(booked_room_ids))

        return JSONResponse(
            content={
                "available_rooms": available_rooms,
                "total_rooms": len(room_ids),
                "booked_rooms": len(booked_room_ids),
            }
        )
    finally:
        conn.close()


@router.get("/api/calendar_availability")
def api_calendar_availability(request: Request, start: str = None, end: str = None, date: str = None):
    start_date = start
    end_date = end
    single_date = date

    if single_date and not (start_date or end_date):
        start_date = end_date = single_date

    if not start_date or not end_date:
        return api_error(
            "Start and end date parameters are required",
            400,
            code="validation_error",
            fields=["start", "end"],
        )

    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return api_error("Invalid date format", 400, code="validation_error", fields=["start", "end"])

    conn = get_db()
    try:
        total_rooms = conn.execute("SELECT COUNT(*) as count FROM rooms WHERE id > 0").fetchone()["count"]

        date_range = []
        current_date = start_date_obj
        while current_date <= end_date_obj:
            date_range.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)

        result = []
        for d in date_range:
            reservation_count = conn.execute(
                """
                SELECT COUNT(*) as count
                FROM reservations r
                WHERE r.date = ?
                  AND r.status NOT IN ('cancelled', 'rejected')
                """,
                (d,),
            ).fetchone()["count"]

            booked_rooms = conn.execute(
                """
                SELECT COUNT(DISTINCT r.room_id) as count
                FROM reservations r
                WHERE r.date = ?
                  AND r.status NOT IN ('cancelled', 'rejected')
                  AND NOT EXISTS (
                    SELECT 1 FROM idle_reservations i
                    WHERE i.reservation_id = r.id AND i.date = r.date
                  )
                """,
                (d,),
            ).fetchone()["count"]

            available_rooms = total_rooms - booked_rooms
            occupancy_percentage = (booked_rooms / total_rooms * 100) if total_rooms > 0 else 0

            result.append(
                {
                    "date": d,
                    "reservationCount": reservation_count,
                    "availableRooms": available_rooms,
                    "totalRooms": total_rooms,
                    "occupancyPercentage": round(occupancy_percentage, 1),
                }
            )

        return JSONResponse(content=result)
    finally:
        conn.close()


@router.post("/api/price_estimate")
async def price_estimate(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    payload = await get_request_payload(request)
    room_id = payload.get("room_id")
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")

    if room_id is None or not start_time or not end_time:
        return api_error(
            "Missing required fields",
            400,
            code="validation_error",
            fields=["room_id", "start_time", "end_time"],
        )

    try:
        room_id_int = int(room_id)
    except Exception:
        return api_error("Invalid room id", 400, code="validation_error", fields=["room_id"])

    try:
        normalized_start, normalized_end, _, _ = normalize_time_range(payload.get("date", ""), start_time, end_time)
    except ValueError as e:
        return api_error(str(e), 400, code="validation_error", fields=["start_time", "end_time"])

    conn = get_db()
    try:
        pricing = compute_pricing(
            conn,
            room_id_int,
            normalized_start,
            normalized_end,
            float(getattr(Config, "TAX_RATE", 0.055)),
        )
        return api_ok({"pricing": pricing})
    finally:
        conn.close()


@router.post("/api/room_suggestion")
async def room_suggestion(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    data = await get_request_payload(request)
    date = data.get("date")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    try:
        num_people = int(data.get("num_people", 0))
    except Exception:
        return api_error("Invalid number of people", 400, code="validation_error", fields=["num_people"])

    if not date or not start_time or not end_time:
        return api_error("Missing required fields", 400, code="validation_error")

    conn = get_db()
    try:
        rooms = conn.execute("SELECT id, capacity FROM rooms WHERE id > 0").fetchall()

        candidates = []
        for room in rooms:
            if room["capacity"] < num_people:
                continue
            conflict = find_conflict(conn, room["id"], date, start_time, end_time)
            if conflict:
                continue
            candidates.append(room["id"])

        return api_ok({"room_ids": candidates})
    finally:
        conn.close()


@router.post("/api/alternative_times")
async def alternative_times(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    data = await get_request_payload(request)
    date = data.get("date")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    room_id = data.get("room_id")

    if not date or not start_time or not end_time or not room_id:
        return api_error("Missing required fields", 400, code="validation_error")

    conn = get_db()
    try:
        try:
            room_id_int = int(room_id)
        except Exception:
            return api_error("Invalid room id", 400, code="validation_error", fields=["room_id"])

        shifts = [-120, -90, -60, -30, 30, 60, 90, 120]
        alternatives = []
        try:
            start_dt, _ = parse_time_safe(start_time)
            end_dt, _ = parse_time_safe(end_time)
        except ValueError as e:
            return api_error(str(e), 400, code="validation_error", fields=["start_time", "end_time"])

        for minutes in shifts:
            shifted_start = (start_dt + timedelta(minutes=minutes)).strftime("%H:%M")
            shifted_end = (end_dt + timedelta(minutes=minutes)).strftime("%H:%M")
            if shifted_end <= shifted_start:
                continue
            conflict = find_conflict(conn, room_id_int, date, shifted_start, shifted_end)
            if not conflict:
                alternatives.append({"start_time": shifted_start, "end_time": shifted_end})

        return api_ok({"alternatives": alternatives})
    finally:
        conn.close()


@router.get("/api/me")
def api_me(request: Request):
    role = request.session.get("role", "guest")
    payload = {
        "is_admin": role == "admin",
        "role": role,
        "can_manage_reservations": role in {"admin", "staff"},
    }
    if role == "customer":
        conn = get_db()
        try:
            user_row = conn.execute(
                "SELECT email_notifications FROM users WHERE id = ?", (request.session.get("user_id"),)
            ).fetchone()
            email_notifications = bool(user_row["email_notifications"]) if user_row else True
            payload.update(
                {
                    "user_id": request.session.get("user_id"),
                    "name": request.session.get("user_name"),
                    "email": request.session.get("user_email"),
                    "email_notifications": email_notifications,
                }
            )
        finally:
            conn.close()
    return api_ok(payload)


@router.post("/api/auth/logout")
def api_logout(request: Request):
    request.session.clear()
    return api_ok(message="Logged out")


@router.get("/login/google")
def login_google(request: Request):
    state = str(uuid.uuid4())
    request.session["oauth_state"] = state

    client_id = getattr(Config, "GOOGLE_CLIENT_ID", "")
    base_url = getattr(Config, "BASE_URL", "")

    if not client_id:
        return api_error("Google OAuth is not configured on this server.", 501, code="not_implemented")

    redirect_uri = f"{base_url}/login/google/callback"
    auth_url = oauth_service.get_google_auth_url(state, redirect_uri, client_id)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/login/google/callback")
def login_google_callback(request: Request, code: str = None, state: str = None):
    if not code or not state:
        return api_error("Missing authorization code or state", 400)

    saved_state = request.session.pop("oauth_state", None)
    if not saved_state or saved_state != state:
        return api_error("Invalid OAuth state (CSRF detected)", 400, code="csrf_error")

    client_id = getattr(Config, "GOOGLE_CLIENT_ID", "")
    client_secret = getattr(Config, "GOOGLE_CLIENT_SECRET", "")
    base_url = getattr(Config, "BASE_URL", "")
    redirect_uri = f"{base_url}/login/google/callback"

    try:
        tokens = oauth_service.exchange_google_code(code, redirect_uri, client_id, client_secret)
        user_info = oauth_service.get_google_user_info(tokens["access_token"])

        google_id = user_info["sub"]
        email = user_info["email"]
        name = user_info.get("name", email.split("@")[0])

        conn = get_db()
        try:
            user = auth_service.get_user_by_google_id(google_id, conn=conn)
            if not user:
                existing_user = auth_service.get_user_by_email(email, conn=conn)
                if existing_user:
                    conn.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, existing_user["id"]))
                    conn.commit()
                    user = auth_service.get_user_by_id(existing_user["id"], conn=conn)
                else:
                    user = auth_service.create_user(
                        email=email, password=None, name=name, google_id=google_id, conn=conn
                    )
        finally:
            conn.close()

        request.session["role"] = "customer"
        request.session["user_id"] = user["id"]
        request.session["user_name"] = user["name"]
        request.session["user_email"] = user["email"]

        # Link guest messages to customer account on login
        session_id = request.session.get("guest_session_id")
        if session_id:
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE direct_messages SET user_id = ? WHERE session_id = ? AND user_id IS NULL",
                    (user["id"], session_id),
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to link guest messages: {e}")
            finally:
                conn.close()

        return RedirectResponse(url="/", status_code=302)
    except Exception as e:
        logger.error(f"Google Login error: {e}")
        return RedirectResponse(url="/?error=google_auth_failed", status_code=302)


@router.post("/api/requests")
async def api_create_request(request: Request, background_tasks: BackgroundTasks):
    role = request.session.get("role")
    if role != "customer" and role not in {"admin", "staff"}:
        return api_error("Login required to submit a booking request", 401, code="auth_required")

    user_id = request.session.get("user_id")
    payload = await get_request_payload(request)

    # We call the core creation logic
    resp = create_pending_request_api(payload, user_id, api_error, api_ok)

    # If request was successful (status 201), schedule background emails
    if resp.status_code == 201:
        res_data = json.loads(resp.body.decode("utf-8"))
        res_dict = res_data.get("reservation")
        if res_dict:
            background_tasks.add_task(email_service.send_request_received, res_dict)
            background_tasks.add_task(email_service.send_staff_notification, res_dict)

    return resp


@router.get("/api/requests/pending")
def api_pending_requests(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM reservations WHERE status = 'pending' ORDER BY requested_at ASC").fetchall()
        return api_ok({"requests": [dict(r) for r in rows]})
    finally:
        conn.close()


@router.post("/api/requests/{reservation_id}/approve")
def api_approve_request(request: Request, reservation_id: int, background_tasks: BackgroundTasks):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        # CONCURRENCY LOCK - Begin Immediate or SELECT FOR UPDATE
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row:
            return api_error("Reservation request not found", 404)

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (row["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch inside transaction lock
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row:
            return api_error("Reservation request not found", 404)

        if row["status"] != "pending":
            return api_error(f"Cannot approve request with status '{row['status']}'", 409)

        conflict = find_conflict(conn, row["room_id"], row["date"], row["start_time"], row["end_time"])
        if conflict:
            return api_error(
                "Room is no longer available for the selected time (conflicts with another confirmed booking)",
                409,
                code="conflict",
                details={"conflict_with": conflict["id"]},
            )

        token = str(uuid.uuid4())
        conn.execute(
            "UPDATE reservations SET status = 'confirmed', cancellation_token = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (token, reservation_id),
        )

        user_id = row["user_id"]
        if user_id:
            message = (
                f"Your reservation request for Room {row['room_id']} on {row['date']} "
                f"({row['start_time']} - {row['end_time']}) has been APPROVED!"
            )
            conn.execute(
                "INSERT INTO notifications (user_id, reservation_id, message) VALUES (?, ?, ?)",
                (user_id, reservation_id, message),
            )

        conn.commit()

        updated_row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        res_dict = dict(updated_row)

        record_reservation_history(conn, reservation_id, "approved", res_dict)
        log_action(
            "reservation.approve", reservation_id=reservation_id, description=f"Approved request {reservation_id}"
        )

        # Publish change for SSE
        publish_sse_event(
            "reservation_approved",
            f"Reservation request {reservation_id} for Room {updated_row['room_id']} "
            f"on {updated_row['date']} has been approved.",
        )

        # Asynchronously send email confirmation if user allowed it
        should_send_email = True
        if user_id:
            user_pref = conn.execute("SELECT email_notifications FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_pref and not user_pref["email_notifications"]:
                should_send_email = False

        if should_send_email:
            background_tasks.add_task(email_service.send_confirmation, res_dict)

        return api_ok(message="Reservation approved")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/api/requests/{reservation_id}/decline")
async def api_decline_request(request: Request, reservation_id: int, background_tasks: BackgroundTasks):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    payload = await get_request_payload(request)
    reason = payload.get("reason", "")

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row:
            return api_error("Reservation request not found", 404)

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (row["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch inside transaction lock
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row:
            return api_error("Reservation request not found", 404)

        if row["status"] != "pending":
            return api_error(f"Cannot decline request with status '{row['status']}'", 409)

        conn.execute(
            "UPDATE reservations SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (reservation_id,),
        )

        user_id = row["user_id"]
        if user_id:
            decline_reason = f" Reason: {reason}" if reason else ""
            message = (
                f"Your reservation request for Room {row['room_id']} on {row['date']} "
                f"({row['start_time']} - {row['end_time']}) was declined.{decline_reason}"
            )
            conn.execute(
                "INSERT INTO notifications (user_id, reservation_id, message) VALUES (?, ?, ?)",
                (user_id, reservation_id, message),
            )

        conn.commit()

        updated_row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        res_dict = dict(updated_row)

        record_reservation_history(conn, reservation_id, "declined", {"reason": reason, "details": res_dict})
        log_action(
            "reservation.decline",
            reservation_id=reservation_id,
            reason=reason,
            description=f"Declined request {reservation_id}",
        )

        # Publish change for SSE
        publish_sse_event(
            "reservation_declined",
            f"Reservation request {reservation_id} for Room {updated_row['room_id']} "
            f"on {updated_row['date']} has been declined.",
        )

        # Asynchronously send email rejection if user allowed it
        should_send_email = True
        if user_id:
            user_pref = conn.execute("SELECT email_notifications FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_pref and not user_pref["email_notifications"]:
                should_send_email = False

        if should_send_email:
            background_tasks.add_task(email_service.send_rejection, res_dict, reason)

        return api_ok(message="Reservation declined")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/cancel/{token}")
def render_cancel_confirm(request: Request, token: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE cancellation_token = ?", (token,)).fetchone()
        if not row:
            return templates.TemplateResponse(
                request=request, name="cancel_confirm.html", context={"error": "Invalid or expired cancellation link."}
            )

        if row["status"] == "cancelled":
            return templates.TemplateResponse(
                request=request, name="cancel_done.html", context={"already_cancelled": True}
            )

        if row["status"] != "confirmed":
            return templates.TemplateResponse(
                request=request,
                name="cancel_confirm.html",
                context={"error": f"Cannot cancel a reservation with status '{row['status']}'."},
            )

        chicago_tz = ZoneInfo("America/Chicago")
        now_local = datetime.now(chicago_tz)

        res_start_hour, res_start_minute = map(int, row["start_time"].split(":"))
        res_date = datetime.strptime(row["date"], "%Y-%m-%d")
        if res_start_hour >= 24:
            res_start_hour -= 24
            res_date += timedelta(days=1)

        res_start_dt = datetime(
            res_date.year, res_date.month, res_date.day, res_start_hour, res_start_minute, tzinfo=chicago_tz
        )
        cutoff_hours = int(getattr(Config, "CANCEL_CUTOFF_HOURS", 2))
        cutoff_time = res_start_dt - timedelta(hours=cutoff_hours)

        can_cancel = now_local <= cutoff_time

        return templates.TemplateResponse(
            request=request,
            name="cancel_confirm.html",
            context={"reservation": dict(row), "can_cancel": can_cancel, "cutoff_hours": cutoff_hours},
        )
    finally:
        conn.close()


@router.post("/cancel/{token}")
def execute_cancel(request: Request, token: str, background_tasks: BackgroundTasks):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE cancellation_token = ?", (token,)).fetchone()
        if not row:
            return api_error("Invalid or expired cancellation token", 404)

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (row["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch inside transaction lock
        row = conn.execute("SELECT * FROM reservations WHERE cancellation_token = ?", (token,)).fetchone()
        if not row:
            return api_error("Invalid or expired cancellation token", 404)

        if row["status"] == "cancelled":
            return templates.TemplateResponse(request=request, name="cancel_done.html", context={})

        if row["status"] != "confirmed":
            return api_error(f"Cannot cancel a reservation with status '{row['status']}'", 409)

        chicago_tz = ZoneInfo("America/Chicago")
        now_local = datetime.now(chicago_tz)

        res_start_hour, res_start_minute = map(int, row["start_time"].split(":"))
        res_date = datetime.strptime(row["date"], "%Y-%m-%d")
        if res_start_hour >= 24:
            res_start_hour -= 24
            res_date += timedelta(days=1)

        res_start_dt = datetime(
            res_date.year, res_date.month, res_date.day, res_start_hour, res_start_minute, tzinfo=chicago_tz
        )
        cutoff_hours = int(getattr(Config, "CANCEL_CUTOFF_HOURS", 2))
        cutoff_time = res_start_dt - timedelta(hours=cutoff_hours)

        if now_local > cutoff_time:
            return api_error(
                f"Reservations can only be cancelled up to {cutoff_hours} hours before the start time.",
                409,
                code="cutoff_exceeded",
            )

        conn.execute(
            "UPDATE reservations SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],)
        )
        conn.commit()

        updated_row = conn.execute("SELECT * FROM reservations WHERE id = ?", (row["id"],)).fetchone()
        res_dict = dict(updated_row)

        record_reservation_history(conn, row["id"], "cancelled_by_customer", res_dict)
        log_action(
            "reservation.cancel_by_customer", reservation_id=row["id"], description=f"Cancelled reservation {row['id']}"
        )

        # Publish change for SSE
        publish_sse_event(
            "reservation_cancelled",
            f"Reservation {row['id']} for Room {row['room_id']} on {row['date']} has been cancelled by Customer.",
        )

        # Asynchronously send email cancellation notice to staff
        background_tasks.add_task(email_service.send_cancellation_notice, res_dict)

        return templates.TemplateResponse(request=request, name="cancel_done.html", context={})

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/api/notifications")
def api_get_notifications(request: Request):
    role = request.session.get("role")
    if role != "customer":
        return api_ok({"notifications": []})

    user_id = request.session.get("user_id")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, message, read, created_at FROM notifications "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        ).fetchall()
        return api_ok({"notifications": [dict(r) for r in rows]})
    finally:
        conn.close()


@router.post("/api/notifications/read")
def api_mark_all_notifications_read(request: Request):
    role = request.session.get("role")
    if role != "customer":
        return api_error("Customer login required", 401, code="auth_required")

    user_id = request.session.get("user_id")
    conn = get_db()
    try:
        conn.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        conn.commit()
        return api_ok(message="All notifications marked as read")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/api/notifications/{notification_id}/read")
def api_mark_notification_read(request: Request, notification_id: int):
    role = request.session.get("role")
    if role != "customer":
        return api_error("Customer login required", 401, code="auth_required")

    user_id = request.session.get("user_id")
    conn = get_db()
    try:
        row = conn.execute("SELECT user_id FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        if not row or row["user_id"] != user_id:
            return api_error("Notification not found", 404)

        conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
        conn.commit()
        return api_ok(message="Notification marked as read")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ---- Direct Messaging API Endpoints ----


@router.get("/api/messages")
def api_get_messages(request: Request, mark_read: bool = False):
    session_id = request.session.get("guest_session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        request.session["guest_session_id"] = session_id

    user_id = request.session.get("user_id")
    role = request.session.get("role")
    is_customer = role == "customer" and user_id is not None

    conn = get_db()
    try:
        if is_customer:
            if mark_read:
                # Mark staff replies as read by user
                conn.execute(
                    "UPDATE direct_messages SET read_by_user = 1 WHERE sender_role = 'staff' "
                    "AND read_by_user = 0 AND (user_id = ? OR session_id = ?)",
                    (user_id, session_id),
                )
                conn.commit()
            rows = conn.execute(
                "SELECT * FROM direct_messages WHERE user_id = ? OR session_id = ? ORDER BY created_at ASC, id ASC",
                (user_id, session_id),
            ).fetchall()
        else:
            if mark_read:
                # Mark staff replies as read by user
                conn.execute(
                    "UPDATE direct_messages SET read_by_user = 1 WHERE sender_role = 'staff' "
                    "AND read_by_user = 0 AND user_id IS NULL AND session_id = ?",
                    (session_id,),
                )
                conn.commit()
            rows = conn.execute(
                "SELECT * FROM direct_messages WHERE user_id IS NULL AND session_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (session_id,),
            ).fetchall()

        messages = []
        for r in rows:
            messages.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "session_id": r["session_id"],
                    "guest_name": r["guest_name"],
                    "guest_email": r["guest_email"],
                    "message": r["message"],
                    "sender_role": r["sender_role"],
                    "read_by_staff": r["read_by_staff"],
                    "read_by_user": r["read_by_user"],
                    "created_at": r["created_at"].isoformat()
                    if hasattr(r["created_at"], "isoformat")
                    else str(r["created_at"]),
                }
            )
        return api_ok({"messages": messages, "session_id": session_id})
    finally:
        conn.close()


@router.post("/api/messages")
async def api_post_message(request: Request):
    session_id = request.session.get("guest_session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        request.session["guest_session_id"] = session_id

    user_id = request.session.get("user_id")
    role = request.session.get("role")
    is_customer = role == "customer" and user_id is not None

    payload = await get_request_payload(request)
    message = payload.get("message")
    if not message or not message.strip():
        return api_error("Message content is required", 400, code="validation_error", fields=["message"])

    guest_name = payload.get("guest_name")
    guest_email = payload.get("guest_email")

    conn = get_db()
    try:
        sender_role = "customer" if is_customer else "guest"
        conn.execute(
            """
            INSERT INTO direct_messages (user_id, session_id, guest_name, guest_email,
                                         message, sender_role, read_by_staff, read_by_user)
            VALUES (?, ?, ?, ?, ?, ?, 0, 1)
            """,
            (user_id if is_customer else None, session_id, guest_name, guest_email, message.strip(), sender_role),
        )
        conn.commit()

        # Publish change for SSE
        publish_sse_event(
            "new_message",
            f"New message from {guest_name or 'Guest'}",
            user_id=user_id if is_customer else None,
            session_id=session_id,
            sender_role=sender_role,
        )

        return api_ok(message="Message sent successfully")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/api/staff/messages")
def api_get_staff_conversations(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM direct_messages ORDER BY created_at ASC, id ASC").fetchall()
        user_rows = conn.execute("SELECT id, name, email FROM users").fetchall()
        user_map = {u["id"]: {"name": u["name"], "email": u["email"]} for u in user_rows}

        conversations = {}
        for r in rows:
            sid = r["session_id"]
            uid = r["user_id"]

            name = None
            email = None
            if uid in user_map:
                name = user_map[uid]["name"]
                email = user_map[uid]["email"]
            else:
                name = r["guest_name"]
                email = r["guest_email"]

            if sid not in conversations:
                conversations[sid] = {
                    "session_id": sid,
                    "name": name or "Guest",
                    "email": email or "",
                    "unread_count": 0,
                    "last_message": "",
                    "last_message_time": "",
                    "last_sender_role": "",
                }

            c = conversations[sid]
            if name and (not c["name"] or c["name"] == "Guest"):
                c["name"] = name
            if email and not c["email"]:
                c["email"] = email

            if r["read_by_staff"] == 0 and r["sender_role"] != "staff":
                c["unread_count"] += 1

            c["last_message"] = r["message"]
            c["last_sender_role"] = r["sender_role"]
            c["last_message_time"] = (
                r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
            )

        sorted_convs = sorted(conversations.values(), key=lambda x: x["last_message_time"], reverse=True)
        return api_ok({"conversations": sorted_convs})
    finally:
        conn.close()


@router.get("/api/staff/messages/{session_id}")
def api_get_staff_conversation(request: Request, session_id: str):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        conn.execute(
            "UPDATE direct_messages SET read_by_staff = 1 WHERE session_id = ? AND read_by_staff = 0",
            (session_id,),
        )
        conn.commit()

        rows = conn.execute(
            "SELECT * FROM direct_messages WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ).fetchall()

        user_id = None
        guest_name = None
        guest_email = None
        for r in rows:
            if r["user_id"]:
                user_id = r["user_id"]
            if r["guest_name"]:
                guest_name = r["guest_name"]
            if r["guest_email"]:
                guest_email = r["guest_email"]

        name = "Guest"
        email = ""
        if user_id:
            user_row = conn.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_row:
                name = user_row["name"]
                email = user_row["email"]
        elif guest_name:
            name = guest_name
            email = guest_email or ""

        messages = []
        for r in rows:
            messages.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "session_id": r["session_id"],
                    "guest_name": r["guest_name"],
                    "guest_email": r["guest_email"],
                    "message": r["message"],
                    "sender_role": r["sender_role"],
                    "read_by_staff": r["read_by_staff"],
                    "read_by_user": r["read_by_user"],
                    "created_at": r["created_at"].isoformat()
                    if hasattr(r["created_at"], "isoformat")
                    else str(r["created_at"]),
                }
            )

        return api_ok({"messages": messages, "name": name, "email": email})
    finally:
        conn.close()


@router.post("/api/staff/messages/{session_id}")
async def api_post_staff_reply(request: Request, session_id: str):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    payload = await get_request_payload(request)
    message = payload.get("message")
    if not message or not message.strip():
        return api_error("Message content is required", 400, code="validation_error", fields=["message"])

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM direct_messages WHERE session_id = ? AND user_id IS NOT NULL LIMIT 1",
            (session_id,),
        ).fetchone()
        user_id = row["user_id"] if row else None

        conn.execute(
            """
            INSERT INTO direct_messages (user_id, session_id, message, sender_role, read_by_staff, read_by_user)
            VALUES (?, ?, ?, 'staff', 1, 0)
            """,
            (user_id, session_id, message.strip()),
        )
        conn.commit()

        # Publish change for SSE
        publish_sse_event(
            "new_message", "New support message", user_id=user_id, session_id=session_id, sender_role="staff"
        )

        return api_ok(message="Reply sent successfully")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.delete("/api/staff/messages/{session_id}")
def api_delete_staff_conversation(request: Request, session_id: str):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        conn.execute("DELETE FROM direct_messages WHERE session_id = ?", (session_id,))
        conn.commit()

        # Publish change for SSE
        publish_sse_event("conversation_removed", "Conversation deleted by Staff", session_id=session_id)

        return api_ok(message="Conversation deleted successfully")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.patch("/api/me/preferences")
async def api_update_preferences(request: Request):
    role = request.session.get("role")
    if role != "customer":
        return api_error("Customer login required", 401, code="auth_required")

    user_id = request.session.get("user_id")
    payload = await get_request_payload(request)
    email_notifications = payload.get("email_notifications")

    if email_notifications is None:
        return api_error("Missing email_notifications parameter", 400, code="validation_error")

    email_notifications_val = 1 if email_notifications else 0

    conn = get_db()
    try:
        if is_postgres_connection(conn):
            conn.execute(
                "UPDATE users SET email_notifications = ?::boolean WHERE id = ?", (bool(email_notifications), user_id)
            )
        else:
            email_notifications_val = 1 if email_notifications else 0
            conn.execute("UPDATE users SET email_notifications = ? WHERE id = ?", (email_notifications_val, user_id))
        conn.commit()
        return api_ok(message="Preferences updated successfully")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.get("/api/me/bookings")
def api_get_my_bookings(request: Request):
    role = request.session.get("role")
    if role != "customer":
        return api_error("Customer login required", 401, code="auth_required")

    user_id = request.session.get("user_id")
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM reservations
            WHERE user_id = ?
            ORDER BY date DESC, start_time DESC
            """,
            (user_id,),
        ).fetchall()

        idle_set = fetch_idle_set(conn)
        bookings = [serialize_reservation_row(r, r["id"] in idle_set) for r in rows]

        # Filter out cancelled/rejected bookings updated > 24 hours ago
        filtered_bookings = []
        now = datetime.now(timezone.utc)
        for b in bookings:
            if b.get("status") in ("cancelled", "rejected"):
                updated_at_str = b.get("updated_at")
                if updated_at_str:
                    try:
                        if isinstance(updated_at_str, str):
                            if "T" in updated_at_str:
                                dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                            else:
                                dt = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        elif isinstance(updated_at_str, datetime):
                            dt = updated_at_str
                        else:
                            dt = None

                        if dt:
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            diff = now - dt
                            if diff.total_seconds() > 24 * 3600:
                                continue
                    except Exception:
                        pass
            filtered_bookings.append(b)

        return api_ok({"bookings": filtered_bookings})
    finally:
        conn.close()


@router.post("/api/me/bookings/{reservation_id}/cancel")
def api_customer_cancel_booking(request: Request, reservation_id: int, background_tasks: BackgroundTasks):
    role = request.session.get("role")
    if role != "customer":
        return api_error("Customer login required", 401, code="auth_required")

    user_id = request.session.get("user_id")
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row or row["user_id"] != user_id:
            return api_error("Reservation not found", 404)

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (row["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch inside transaction lock
        row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not row or row["user_id"] != user_id:
            return api_error("Reservation not found", 404)

        if row["status"] == "cancelled":
            return api_ok(message="Reservation is already cancelled")

        if row["status"] == "confirmed":
            chicago_tz = ZoneInfo("America/Chicago")
            now_local = datetime.now(chicago_tz)

            res_start_hour, res_start_minute = map(int, row["start_time"].split(":"))
            res_date = datetime.strptime(row["date"], "%Y-%m-%d")
            if res_start_hour >= 24:
                res_start_hour -= 24
                res_date += timedelta(days=1)

            res_start_dt = datetime(
                res_date.year, res_date.month, res_date.day, res_start_hour, res_start_minute, tzinfo=chicago_tz
            )
            cutoff_hours = int(getattr(Config, "CANCEL_CUTOFF_HOURS", 2))
            cutoff_time = res_start_dt - timedelta(hours=cutoff_hours)

            if now_local > cutoff_time:
                return api_error(
                    f"Confirmed reservations can only be cancelled up to {cutoff_hours} hours before start time.",
                    409,
                    code="cutoff_exceeded",
                )

        conn.execute(
            "UPDATE reservations SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (reservation_id,),
        )
        conn.commit()

        updated_row = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        res_dict = dict(updated_row)
        record_reservation_history(conn, reservation_id, "cancelled_by_customer", res_dict)
        log_action(
            "reservation.cancel_by_customer",
            reservation_id=reservation_id,
            description=f"Cancelled booking {reservation_id}",
        )

        # Publish change for SSE
        publish_sse_event(
            "reservation_cancelled",
            f"Reservation {reservation_id} for Room {row['room_id']} on {row['date']} has been cancelled by Customer.",
        )

        if row["status"] == "confirmed":
            background_tasks.add_task(email_service.send_cancellation_notice, res_dict)

        return api_ok(message="Reservation cancelled successfully")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ---- Legacy compatibility REST endpoints ----


@router.post("/login")
async def admin_login(request: Request):
    payload = await get_request_payload(request)
    username = payload.get("username")
    password = payload.get("password")
    role = None

    if username == getattr(Config, "ADMIN_USERNAME", "admin") and password == getattr(
        Config, "ADMIN_PASSWORD", "admin"
    ):
        role = "admin"
    elif username == getattr(Config, "STAFF_USERNAME", "staff") and password == getattr(
        Config, "STAFF_PASSWORD", "staff"
    ):
        role = "staff"

    if role:
        request.session["role"] = role
        return JSONResponse(content={"message": f"Logged in as {role}", "role": role})

    return api_error("Invalid credentials", 401, code="invalid_credentials")


@router.post("/logout")
def admin_logout(request: Request):
    request.session.clear()
    return JSONResponse(content={"message": "Logged out"})


@router.route("/reservation", methods=["GET", "POST"])
async def reservation(request: Request):
    if request.method == "POST":
        auth_err = check_worker(request)
        if auth_err:
            return auth_err
        payload = await get_request_payload(request)
        return create_reservation_api_payload(
            payload,
            api_error,
            api_ok,
            success_message="Reservation created successfully",
            status_code=200,
            include_success=False,
        )

    return RedirectResponse(url="/improved", status_code=302)


@router.get("/get_reservation/{reservation_id}")
def legacy_get_reservation(request: Request, reservation_id: int):
    conn = get_db()
    try:
        reservation = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if reservation is None:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        role = request.session.get("role", "guest")
        user_id = request.session.get("user_id")
        is_worker = role in ("admin", "staff")
        is_owner = user_id is not None and reservation["user_id"] == user_id

        if not is_worker and not is_owner:
            return JSONResponse(
                content={
                    "id": reservation["id"],
                    "date": reservation["date"],
                    "start_time": reservation["start_time"],
                    "end_time": reservation["end_time"],
                    "num_people": reservation["num_people"],
                    "contact_name": "Reserved",
                    "contact_phone": "Masked",
                    "contact_email": "Masked",
                    "room_id": reservation["room_id"],
                    "language": reservation["language"],
                    "notes": "",
                    "status": reservation["status"],
                    "total_cost": reservation["total_cost"],
                    "is_owner": False,
                }
            )

        return JSONResponse(
            content={
                "id": reservation["id"],
                "date": reservation["date"],
                "start_time": reservation["start_time"],
                "end_time": reservation["end_time"],
                "num_people": reservation["num_people"],
                "contact_name": reservation["contact_name"],
                "contact_phone": reservation["contact_phone"],
                "contact_email": reservation["contact_email"],
                "room_id": reservation["room_id"],
                "language": reservation["language"],
                "notes": reservation["notes"],
                "status": reservation["status"],
                "total_cost": reservation["total_cost"],
                "is_owner": is_owner,
            }
        )
    finally:
        conn.close()


@router.post("/delete_reservation/{reservation_id}")
def legacy_delete_reservation(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    conn = get_db()
    try:
        reservation = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not reservation:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (reservation["room_id"],))
        else:
            conn.execute("BEGIN IMMEDIATE")

        conn.execute("DELETE FROM idle_reservations WHERE reservation_id = ?", (reservation_id,))
        conn.execute("DELETE FROM reservation_history WHERE reservation_id = ?", (reservation_id,))
        conn.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
        conn.commit()

        log_action(
            "reservation.delete",
            reservation_id=reservation_id,
            date=reservation["date"],
            room_id=reservation["room_id"],
        )

        # Publish change for SSE
        publish_sse_event(
            "reservation_deleted",
            f"Reservation {reservation_id} for Room {reservation['room_id']} "
            f"on {reservation['date']} has been deleted by Staff.",
        )

        return JSONResponse(
            content={"message": "Reservation deleted successfully", "id": reservation_id}, status_code=200
        )
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/update_reservation/{reservation_id}")
async def legacy_update_reservation(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err

    payload = await get_request_payload(request)
    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not existing:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        room_id = payload.get("room_id", existing["room_id"])

        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (room_id,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Refetch inside lock
        existing = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not existing:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        start_time_raw = payload.get("start_time", existing["start_time"])
        end_time_raw = payload.get("end_time", existing["end_time"])
        date = payload.get("date", existing["date"])

        try:
            room_id = int(room_id)
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid room id", "fields": ["room_id"]})

        try:
            normalized_start, normalized_end, _, _ = normalize_time_range(date, start_time_raw, end_time_raw)
        except ValueError as e:
            return JSONResponse(
                status_code=400, content={"error": str(e), "fields": ["start_time", "end_time", "date"]}
            )

        conflict = find_conflict(conn, room_id, date, normalized_start, normalized_end, exclude_id=reservation_id)
        if conflict:
            return JSONResponse(
                status_code=409, content={"error": "The selected time slot is already occupied by another reservation"}
            )

        num_people = payload.get("num_people", existing["num_people"])
        try:
            num_people = int(num_people)
        except Exception:
            return JSONResponse(
                status_code=400, content={"error": "Invalid number of people", "fields": ["num_people"]}
            )

        from services.reservations import validate_room_capacity

        ok, msg, _ = validate_room_capacity(conn, room_id, num_people)
        if not ok:
            return JSONResponse(status_code=400, content={"error": msg})

        time_or_room_changed = (
            normalized_start != existing["start_time"]
            or normalized_end != existing["end_time"]
            or room_id != existing["room_id"]
        )

        if time_or_room_changed:
            from services.pricing import calculate_cost

            total_cost = calculate_cost(
                conn, room_id, normalized_start, normalized_end, float(getattr(Config, "TAX_RATE", 0.055))
            )
        else:
            total_cost = existing["total_cost"]

        conn.execute(
            """UPDATE reservations
               SET room_id = ?, date = ?, start_time = ?, end_time = ?,
                   contact_name = ?, contact_phone = ?, contact_email = ?,
                   num_people = ?, language = ?, notes = ?, total_cost = ?
               WHERE id = ?""",
            (
                room_id,
                date,
                normalized_start,
                normalized_end,
                payload.get("contact_name", existing["contact_name"]),
                payload.get("contact_phone", existing["contact_phone"]),
                payload.get("contact_email", existing["contact_email"]),
                num_people,
                payload.get("language", existing["language"]),
                payload.get("notes", existing["notes"]),
                total_cost,
                reservation_id,
            ),
        )
        conn.commit()

        updated = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()

        record_reservation_history(conn, reservation_id, "updated", serialize_reservation_row(updated))
        log_action(
            "reservation.update",
            reservation_id=reservation_id,
            room_id=room_id,
            date=date,
            start_time=normalized_start,
            end_time=normalized_end,
            num_people=num_people,
        )

        # Publish change for SSE
        role = request.session.get("role", "guest")
        updated_by = "Staff" if role in ("admin", "staff") else "Customer"
        publish_sse_event("reservation_updated", f"Reservation {reservation_id} updated by {updated_by}.")

        return JSONResponse(
            content={"message": "Reservation updated successfully", "reservation": serialize_reservation_row(updated)},
            status_code=200,
        )
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/move_to_idle/{reservation_id}")
def move_to_idle(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err
    conn = get_db()
    try:
        if is_postgres_connection(conn):
            conn.execute("BEGIN")
        else:
            conn.execute("BEGIN IMMEDIATE")

        reservation = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not reservation:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        existing = conn.execute(
            "SELECT * FROM idle_reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if existing:
            return JSONResponse(content={"message": "Reservation already in idle area"})

        conn.execute(
            "INSERT INTO idle_reservations (reservation_id, date) VALUES (?, ?)",
            (reservation_id, reservation["date"]),
        )
        conn.commit()

        # Publish change for SSE
        publish_sse_event("reservation_moved_to_idle", f"Reservation {reservation_id} moved to idle queue by Staff.")

        return JSONResponse(content={"success": True})
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/remove_from_idle/{reservation_id}")
def remove_from_idle(request: Request, reservation_id: int):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err
    conn = get_db()
    try:
        if is_postgres_connection(conn):
            conn.execute("BEGIN")
        else:
            conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            "SELECT * FROM idle_reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if not existing:
            return JSONResponse(status_code=404, content={"error": "Reservation not found in idle area"})

        conn.execute("DELETE FROM idle_reservations WHERE reservation_id = ?", (reservation_id,))
        conn.commit()

        # Publish change for SSE
        publish_sse_event(
            "reservation_removed_from_idle", f"Reservation {reservation_id} removed from idle queue by Staff."
        )

        return JSONResponse(content={"success": True})
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@router.post("/move_reservation")
async def move_reservation(request: Request):
    auth_err = check_worker(request)
    if auth_err:
        return auth_err
    payload = await get_request_payload(request)
    reservation_id = payload.get("reservation_id")
    room_id = payload.get("room_id")
    date = payload.get("date")

    if reservation_id is None or room_id is None or date is None:
        return JSONResponse(status_code=400, content={"error": "Missing required fields"})

    try:
        reservation_id = int(reservation_id)
        room_id = int(room_id)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid field types"})

    conn = get_db()
    try:
        if is_postgres_connection(conn):
            conn.execute("SELECT id FROM rooms WHERE id = ? FOR UPDATE", (room_id,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        reservation = conn.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if not reservation:
            return JSONResponse(status_code=404, content={"error": "Reservation not found"})

        # Calculate duration
        res_start_parsed, _ = parse_time_safe(reservation["start_time"])
        res_end_parsed, is_extended = parse_time_safe(reservation["end_time"])
        res_start_mins = res_start_parsed.hour * 60 + res_start_parsed.minute
        res_end_mins = res_end_parsed.hour * 60 + res_end_parsed.minute
        if is_extended or res_end_mins <= res_start_mins:
            res_end_mins += 24 * 60
        duration_mins = res_end_mins - res_start_mins

        # Determine new start time
        if "hour" in payload:
            try:
                hour = int(payload["hour"])
                new_start_time = f"{hour:02d}:00"
            except Exception:
                return JSONResponse(status_code=400, content={"error": "Invalid hour"})
        elif "start_time" in payload:
            new_start_time = payload["start_time"]
        else:
            return JSONResponse(status_code=400, content={"error": "Missing hour or start_time"})

        # Determine new end time based on duration
        new_start_parsed, _ = parse_time_safe(new_start_time)
        new_start_mins = new_start_parsed.hour * 60 + new_start_parsed.minute
        new_end_mins = new_start_mins + duration_mins
        new_end_hour = new_end_mins // 60
        new_end_minute = new_end_mins % 60
        new_end_time = f"{new_end_hour:02d}:{new_end_minute:02d}"

        # Normalize and validate time range
        try:
            normalized_start, normalized_end, start_minutes, end_minutes = normalize_time_range(
                date, new_start_time, new_end_time
            )
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

        # Check blackout windows
        blocked, win = is_blackout(date, normalized_start, normalized_end, room_id)
        if blocked:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "message": "The selected time slot is blocked by a blackout window.",
                        "code": "blackout",
                    },
                    "conflict": True,
                },
            )

        # Check conflicts
        conflict = find_conflict(conn, room_id, date, normalized_start, normalized_end, exclude_id=reservation_id)
        if conflict:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "message": "The selected time slot is already occupied",
                        "code": "conflict",
                    },
                    "conflict": True,
                },
            )

        # Clear from idle reservations if it was in there
        conn.execute("DELETE FROM idle_reservations WHERE reservation_id = ?", (reservation_id,))

        conn.execute(
            """
            UPDATE reservations
            SET room_id = ?, start_time = ?, end_time = ?, date = ?
            WHERE id = ?
            """,
            (room_id, normalized_start, normalized_end, date, reservation_id),
        )
        conn.commit()

        # Publish change for SSE
        role = request.session.get("role", "guest")
        assigned_by = "Staff" if role in ("admin", "staff") else "Customer"
        publish_sse_event(
            "reservation_assigned",
            f"Reservation {reservation_id} rescheduled/assigned to Room {room_id} on {date} by {assigned_by}.",
        )

        return JSONResponse(
            content={
                "message": "Reservation moved successfully",
                "reservation": {
                    "id": reservation_id,
                    "room_id": room_id,
                    "start_time": normalized_start,
                    "end_time": normalized_end,
                    "date": date,
                },
            }
        )
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ---- SSE Stream Endpoint ----


@router.get("/api/live_updates")
async def live_updates(request: Request):
    q = sse_broker.subscribe()

    async def event_generator():
        try:
            while True:
                event_type = await q.get()
                yield {"event": "message", "data": json.dumps({"type": event_type})}
        except asyncio.CancelledError:
            pass
        finally:
            sse_broker.unsubscribe(q)

    return EventSourceResponse(event_generator())


# ---- Test Router Endpoints (only enabled when testing is active) ----


@router.post("/api/test/set_session")
async def api_test_set_session(request: Request):
    if not getattr(Config, "TESTING", False):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    payload = await request.json()
    request.session.clear()
    for k, v in payload.items():
        request.session[k] = v
    return {"status": "ok"}


@router.get("/api/test/get_session")
async def api_test_get_session(request: Request):
    if not getattr(Config, "TESTING", False):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return dict(request.session)
