import sys
import os
from pathlib import Path
from contextlib import contextmanager

# Set DATABASE_URL to empty so tests use SQLite by default
os.environ["DATABASE_URL"] = ""

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Now import the FastAPI app, Config, and TestClient
from app import app  # noqa: E402
from config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class AppConfigDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        setattr(Config, key, value)
        if key == "DATABASE" or key == "DATABASE_URL":
            import services.db
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            database_url = getattr(Config, "DATABASE_URL", None)
            if database_url and database_url.startswith(("postgres://", "postgresql://")):
                if database_url.startswith("postgres://"):
                    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
                else:
                    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
                services.db.engine = create_engine(database_url, pool_pre_ping=True)
            else:
                db_path = getattr(Config, "DATABASE", "karaoke.db")
                services.db.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
            services.db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=services.db.engine)

    def update(self, *args, **kwargs):
        for k, v in dict(*args, **kwargs).items():
            self[k] = v

    def get(self, key, default=None):
        return getattr(Config, key, super().get(key, default))


# Initialize app.config dictionary
app.config = AppConfigDict()
for k in dir(Config):
    if not k.startswith("_"):
        try:
            app.config[k] = getattr(Config, k)
        except Exception:
            pass


class CompatibleResponse:
    def __init__(self, response):
        self._response = response

    @property
    def status_code(self):
        return self._response.status_code

    @property
    def headers(self):
        return self._response.headers

    @property
    def text(self):
        return self._response.text

    @property
    def content(self):
        return self._response.content

    @property
    def data(self):
        return self._response.content

    def get_data(self, as_text=False):
        if as_text:
            return self._response.text
        return self._response.content

    def get_json(self):
        return self._response.json()

    def json(self):
        return self._response.json()


class CompatibleTestClient:
    def __init__(self, client):
        self._client = client

    def get(self, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        if "content_type" in kwargs:
            headers = kwargs.setdefault("headers", {})
            headers["Content-Type"] = kwargs.pop("content_type")
        return CompatibleResponse(self._client.get(*args, **kwargs))

    def post(self, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        if "content_type" in kwargs:
            headers = kwargs.setdefault("headers", {})
            headers["Content-Type"] = kwargs.pop("content_type")
        return CompatibleResponse(self._client.post(*args, **kwargs))

    def patch(self, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        if "content_type" in kwargs:
            headers = kwargs.setdefault("headers", {})
            headers["Content-Type"] = kwargs.pop("content_type")
        return CompatibleResponse(self._client.patch(*args, **kwargs))

    def delete(self, *args, **kwargs):
        kwargs.setdefault("follow_redirects", False)
        if "content_type" in kwargs:
            headers = kwargs.setdefault("headers", {})
            headers["Content-Type"] = kwargs.pop("content_type")
        return CompatibleResponse(self._client.delete(*args, **kwargs))

    @contextmanager
    def session_transaction(self):
        try:
            resp = self._client.get("/api/test/get_session")
            session_dict = resp.json() if resp.status_code == 200 else {}
        except Exception:
            session_dict = {}

        yield session_dict

        self._client.post("/api/test/set_session", json=session_dict)


def mock_test_client():
    client = TestClient(app)
    Config.TESTING = True
    app.config["TESTING"] = True
    app.state.testing = True
    return CompatibleTestClient(client)


# Attach mock helpers to app object
app.test_client = mock_test_client


@contextmanager
def dummy_app_context():
    yield


app.app_context = dummy_app_context


@contextmanager
def compatible_test_request_context(path="/", method="GET", **kwargs):
    from services.reservations import request_meta

    token = request_meta.set(
        {
            "path": path.split("?")[0] if path else "/",
            "method": method,
            "request_id": "test-request-id",
            "role": "guest",
        }
    )
    try:
        yield
    finally:
        request_meta.reset(token)


app.test_request_context = compatible_test_request_context
