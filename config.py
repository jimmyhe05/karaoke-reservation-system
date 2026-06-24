import os
from dotenv import load_dotenv
import json

# Load environment variables from .env if present
load_dotenv()


class Config:
    """Central application configuration.

    - SECRET_KEY: Flask session/signing key (set in .env for prod)
    - DATABASE_URL: PostgreSQL connection URL for production
    - DATABASE: SQLite file path used when DATABASE_URL is not set
    - TAX_RATE: Sales tax rate as float (e.g., 0.055 for 5.5%)
    - LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)
    - ADMIN_USERNAME / ADMIN_PASSWORD: Simple admin auth gate for mutating routes
    """

    APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL")
    DATABASE = os.getenv("DATABASE", "karaoke.db")
    TAX_RATE = float(os.getenv("TAX_RATE", "0.055"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # json or text
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

    # Simple secondary role for demos
    STAFF_USERNAME = os.getenv("STAFF_USERNAME", "staff")
    STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "staff")

    # Blackout/maintenance windows JSON list:
    # {"date": "YYYY-MM-DD", "room_id": optional int,
    #  "start_time": optional HH:MM, "end_time": optional HH:MM}
    _blackout_raw = os.getenv("BLACKOUT_WINDOWS", "[]")
    try:
        BLACKOUT_WINDOWS = json.loads(_blackout_raw)
        if not isinstance(BLACKOUT_WINDOWS, list):
            BLACKOUT_WINDOWS = []
    except Exception:
        BLACKOUT_WINDOWS = []

    # Flask settings
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    TESTING = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = (
        os.getenv(
            "SESSION_COOKIE_SECURE",
            "true" if APP_ENV in {"prod", "production"} else "false",
        ).lower()
        == "true"
    )

    # Google OAuth 2.0 configuration
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # SMTP Mail configuration
    MAIL_SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
    MAIL_SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "587"))
    MAIL_SMTP_USER = os.getenv("MAIL_SMTP_USER", "")
    MAIL_SMTP_PASS = os.getenv("MAIL_SMTP_PASS", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "")

    # Reservation Operations config
    STAFF_NOTIFY_EMAIL = os.getenv("STAFF_NOTIFY_EMAIL", "")
    CANCEL_CUTOFF_HOURS = int(os.getenv("CANCEL_CUTOFF_HOURS", "2"))
    BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
