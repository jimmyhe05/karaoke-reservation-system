import os
import sys
import re
import uuid
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# Ensure project root is in sys.path
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import Config
from services.db import get_db, init_db
from services.validation import parse_time_safe, normalize_time_range, slots_overlap, find_conflict

from services.pricing import compute_pricing

from services.reservations import (
    get_today_stats,
    request_meta,
)
from routes.api import router as api_router


# ---- Logging setup ----

class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        base = {
            "time": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
        }
        meta = request_meta.get()
        if meta:
            base["path"] = meta.get("path", "")
            base["method"] = meta.get("method", "")
            base["request_id"] = meta.get("request_id", "")
        return json.dumps(base)


def configure_logging(flask_app=None):
    config_source = flask_app.config if (flask_app is not None and hasattr(flask_app, "config")) else Config
    
    def get_config_val(key):
        if hasattr(config_source, "get"):
            return config_source.get(key)
        return getattr(config_source, key, None)

    level_name = str(get_config_val("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = get_config_val("LOG_FORMAT") or "json"

    logger = flask_app.logger if (flask_app is not None and hasattr(flask_app, "logger")) else logging.getLogger("app")
    
    # For FastAPI app objects or mock compatibility:
    if flask_app is not None and not hasattr(flask_app, "logger"):
        flask_app.logger = logging.getLogger("app")
        logger = flask_app.logger

    logger.handlers = []
    
    handler = logging.StreamHandler()
    if log_format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


configure_logging()
logger = logging.getLogger("app")


# ---- Security validation ----

def validate_security_config(flask_app=None):
    """Fail closed in production when unsafe placeholder credentials are active."""
    config_source = flask_app.config if (flask_app is not None and hasattr(flask_app, "config")) else Config
    
    def get_config_val(key):
        if hasattr(config_source, "get"):
            return config_source.get(key)
        return getattr(config_source, key, None)

    secret_key = get_config_val("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set (see .env)")
        
    if get_config_val("TESTING"):
        return

    weak_values = {
        "SECRET_KEY": {"dev-change-me", "change-me", "change-me-in-prod", "karaoke"},
        "ADMIN_PASSWORD": {"admin", "password", "change-me", "change-me-in-prod"},
        "STAFF_PASSWORD": {"staff", "password", "change-me", "change-me-in-prod"},
    }
    weak_keys = [
        key
        for key, placeholders in weak_values.items()
        if str(get_config_val(key) or "").strip() in placeholders
    ]
    if not weak_keys:
        return

    message = (
        "Unsafe placeholder configuration detected for "
        f"{', '.join(weak_keys)}. Update .env before deploying."
    )
    if get_config_val("APP_ENV") in {"prod", "production"}:
        raise RuntimeError(message)
    logger.warning(message)


validate_security_config()


# ---- Lifespan context manager ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    
    # Run data seeding if db is empty (SQLite only by default)
    conn = get_db()
    try:
        # Seed logic
        pass
    finally:
        conn.close()
        
    yield
    # Shutdown


# ---- FastAPI App initialization ----

app = FastAPI(lifespan=lifespan)
app.logger = logger

# Add session middleware (compatibility with Flask sessions)
# ---- Middleware for request context metadata ----

@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    
    role = request.session.get("role", "guest")
    request_meta.set({
        "path": request.url.path,
        "method": request.method,
        "request_id": request_id,
        "role": role,
    })
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Add session middleware (compatibility with Flask sessions)
app.add_middleware(
    SessionMiddleware,
    secret_key=Config.SECRET_KEY,
    session_cookie="session",
    same_site=Config.SESSION_COOKIE_SAMESITE.lower(),
    https_only=Config.SESSION_COOKIE_SECURE,
)



# ---- Static files and Templates ----

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.globals["APP_ENV"] = getattr(Config, "APP_ENV", "development")
templates.env.globals["config"] = Config

from jinja2 import pass_context
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




# ---- Helpers ----

def normalize_date_path(date_str):
    """Convert MM-DD-YYYY to YYYY-MM-DD."""
    try:
        dt = datetime.strptime(date_str, "%m-%d-%Y").date()
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid date path format")


def get_rooms_with_reservations(selected_date=None):
    conn = get_db()
    try:
        if selected_date is None:
            selected_date = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")

        rooms = conn.execute("SELECT * FROM rooms WHERE id > 0 ORDER BY id").fetchall()

        reservations = conn.execute(
            """
            SELECT * FROM reservations
            WHERE date = ? AND status NOT IN ('cancelled', 'rejected')
            ORDER BY start_time
            """,
            (selected_date,),
        ).fetchall()

        idle_reservations_ids = conn.execute(
            """
            SELECT reservation_id FROM idle_reservations
            WHERE date = ?
            """,
            (selected_date,),
        ).fetchall()

        idle_reservation_ids_set = {row["reservation_id"] for row in idle_reservations_ids}

        rooms_with_reservations = []
        for room in rooms:
            room_reservations = []
            for reservation in reservations:
                if reservation["id"] in idle_reservation_ids_set:
                    continue

                if reservation["room_id"] == room["id"]:
                    start_time, _ = parse_time_safe(reservation["start_time"])
                    end_time, is_extended = parse_time_safe(reservation["end_time"])

                    if is_extended or end_time <= start_time:
                        end_time_with_day = end_time.replace(day=start_time.day + 1)
                        duration = (end_time_with_day - start_time).total_seconds() / 3600
                    else:
                        duration = (end_time - start_time).total_seconds() / 3600

                    room_reservations.append(
                        {
                            "id": reservation["id"],
                            "contact_name": reservation["contact_name"],
                            "num_people": reservation["num_people"],
                            "start_time": reservation["start_time"],
                            "end_time": reservation["end_time"],
                            "start_hour": start_time.hour,
                            "duration": duration,
                        }
                    )

            rooms_with_reservations.append(
                {"id": room["id"], "name": room["name"], "reservations": room_reservations}
            )

        idle_reservations = []
        if idle_reservations_ids:
            idle_res_list = ", ".join(["?" for _ in idle_reservations_ids])
            idle_res_ids = [row["reservation_id"] for row in idle_reservations_ids]

            if idle_res_ids:
                idle_res_data = conn.execute(
                    f"""
                    SELECT * FROM reservations
                    WHERE id IN ({idle_res_list}) AND status NOT IN ('cancelled', 'rejected')
                    """,
                    idle_res_ids,
                ).fetchall()

                for reservation in idle_res_data:
                    start_time, _ = parse_time_safe(reservation["start_time"])
                    end_time, is_extended = parse_time_safe(reservation["end_time"])

                    if is_extended or end_time <= start_time:
                        end_time_with_day = end_time.replace(day=start_time.day + 1)
                        duration = (end_time_with_day - start_time).total_seconds() / 3600
                    else:
                        duration = (end_time - start_time).total_seconds() / 3600

                    idle_reservations.append(
                        {
                            "id": reservation["id"],
                            "contact_name": reservation["contact_name"],
                            "num_people": reservation["num_people"],
                            "start_time": reservation["start_time"],
                            "end_time": reservation["end_time"],
                            "start_hour": start_time.hour,
                            "duration": duration,
                            "room_id": reservation["room_id"],
                        }
                    )

        return {"rooms": rooms_with_reservations, "idle_reservations": idle_reservations}
    finally:
        conn.close()


# ---- HTML View Routes ----

@app.get("/")
def index():
    today_path = datetime.now(ZoneInfo("America/Chicago")).strftime("%m-%d-%Y")
    return RedirectResponse(url=f"/{today_path}", status_code=302)


@app.get("/improved")
def improved_reservation(date: str = None):
    try:
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
        else:
            dt = datetime.now(ZoneInfo("America/Chicago"))
    except ValueError:
        dt = datetime.now(ZoneInfo("America/Chicago"))
    return RedirectResponse(url=f"/{dt.strftime('%m-%d-%Y')}", status_code=302)


@app.get("/{date_str}")
def reservation_by_date(request: Request, date_str: str):
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", date_str):
        raise HTTPException(status_code=404, detail="Not Found")
        
    try:
        iso_date = normalize_date_path(date_str)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found")
        
    data = get_rooms_with_reservations(iso_date)
    conn = get_db()
    try:
        stats = get_today_stats(conn, iso_date)
    finally:
        conn.close()
        
    return templates.TemplateResponse(
        request=request,
        name="reservation.html",
        context={
            "rooms": data["rooms"],
            "idle_reservations": data["idle_reservations"],
            "selected_date": iso_date,
            "today_stats": stats,
        }
    )



# Register API & REST routes router
app.include_router(api_router)


# ---- CLI execution compatibility ----

if __name__ == "__main__":
    import uvicorn
    # If running with CLI commands: python app.py init-db
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "init-db":
            init_db()
            print("Initialized database schema and indexes.")
        elif cmd == "seed-sample":
            target_date = sys.argv[2] if len(sys.argv) > 2 else datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
            # Reuse core create logic via a direct connection
            conn = get_db()
            try:
                # Seed rooms 1, 2, 3 if not present
                conn.execute("INSERT OR IGNORE INTO rooms (id, name, capacity, hourly_rate, peak_hour_rate) VALUES (1, 'Room 1', 8, 35, 50)")
                conn.execute("INSERT OR IGNORE INTO rooms (id, name, capacity, hourly_rate, peak_hour_rate) VALUES (2, 'Room 2', 8, 35, 50)")
                conn.execute("INSERT OR IGNORE INTO rooms (id, name, capacity, hourly_rate, peak_hour_rate) VALUES (3, 'Room 3', 8, 35, 50)")
                conn.commit()
                print(f"Sample database seeded for date: {target_date}")
            finally:
                conn.close()
        else:
            print(f"Unknown CLI command: {cmd}")
    else:
        uvicorn.run("app:app", host="127.0.0.1", port=5001, reload=True)
