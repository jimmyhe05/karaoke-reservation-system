import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


class Config:
    """Central application configuration.

    - SECRET_KEY: Flask session/signing key (set in .env for prod)
    - DATABASE: SQLite file path
    - TAX_RATE: Sales tax rate as float (e.g., 0.055 for 5.5%)
    """

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    DATABASE = os.getenv("DATABASE", "karaoke.db")
    TAX_RATE = float(os.getenv("TAX_RATE", "0.055"))

    # Flask settings
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    TESTING = False
