import sqlite3
from flask import g, current_app


class PostgresConnection:
    """Small compatibility wrapper for the app's sqlite-style query calls."""

    is_postgres = True

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=()):
        return self._conn.execute(_postgres_placeholders(query), params)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


def _postgres_placeholders(query):
    """Translate sqlite qmark placeholders to psycopg placeholders."""
    return query.replace("?", "%s")


def is_postgres_connection(conn):
    return getattr(conn, "is_postgres", False)


def _connect_postgres(database_url):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL requires psycopg. Run `pip install -r requirements.txt`."
        ) from exc

    return PostgresConnection(psycopg.connect(database_url, row_factory=dict_row))


def get_db():
    """Get a database connection bound to the Flask app context."""
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL")
        if database_url and database_url.startswith(("postgres://", "postgresql://")):
            g.db = _connect_postgres(database_url)
        else:
            db_path = current_app.config.get("DATABASE")
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON;")
            g.db.execute("PRAGMA journal_mode = WAL;")
    return g.db


def close_db(error=None):
    """Close the database connection if present."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Initialize the database schema and indexes (idempotent)."""
    db = get_db()
    schema_file = "schema_postgres.sql" if is_postgres_connection(db) else "schema.sql"
    with current_app.open_resource(schema_file, mode="r") as f:
        schema = f.read()
    if is_postgres_connection(db):
        for statement in _split_sql_statements(schema):
            db.execute(statement)
    else:
        db.cursor().executescript(schema)
    db.commit()

    from migrations.runner import run_migrations

    run_migrations(db)


def _split_sql_statements(script):
    statements = []
    current = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).rstrip(";"))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements
