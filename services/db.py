import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Ensure the project root is on sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith(("postgres://", "postgresql://")):
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    else:
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url, pool_pre_ping=True)
else:
    db_path = os.getenv("DATABASE", "karaoke.db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class DictRowWrapper:
    def __init__(self, row_tuple, description):
        self._row = row_tuple
        self._keys = [col[0] for col in description]
        self._dict = {col[0]: val for col, val in zip(description, row_tuple)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._dict[key]

    def __contains__(self, key):
        return key in self._dict

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._keys

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

    def __iter__(self):
        return iter(self._dict)

    def __repr__(self):
        return repr(self._dict)


class CompatibleCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if hasattr(row, "keys") or isinstance(row, dict):
            return row
        # Convert sqlite row or tuple to DictRowWrapper
        if type(row).__name__ == "Row" or isinstance(row, tuple):
            return DictRowWrapper(tuple(row), self.cursor.description)
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        first = rows[0]
        if hasattr(first, "keys") or isinstance(first, dict):
            return rows
        if type(first).__name__ == "Row" or isinstance(first, tuple):
            return [DictRowWrapper(tuple(r), self.cursor.description) for r in rows]
        return rows

    @property
    def lastrowid(self):
        return getattr(self.cursor, "lastrowid", None)


class SqlAlchemyConnectionAdapter:
    """Wrapper to make SQLAlchemy session match Flask SQLite/Postgres connection interface."""
    
    def __init__(self, session: Session):
        self.session = session
        self.is_postgres = (session.bind.dialect.name == "postgresql")

    def execute(self, query, params=None):
        if params is None:
            params = ()
        
        if isinstance(query, str):
            # Check if using postgres placeholders
            dbapi_conn = self.session.connection().connection
            cursor = dbapi_conn.cursor()

            
            if self.is_postgres:
                # Translate '?' to '%s'
                query_processed = query.replace("?", "%s")
                cursor.execute(query_processed, params)
            else:
                cursor.execute(query, params)
            return CompatibleCursor(cursor)
        else:
            return self.session.execute(query, params)

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def close(self):
        self.session.close()


def get_db() -> SqlAlchemyConnectionAdapter:
    """Legacy helper returning connection wrapper."""
    return SqlAlchemyConnectionAdapter(SessionLocal())


def _postgres_placeholders(query):
    """Translate sqlite qmark placeholders to psycopg placeholders."""
    return query.replace("?", "%s")


def is_postgres_connection(conn):

    return getattr(conn, "is_postgres", False)


def close_db(error=None):
    pass


def init_db():
    """Initialize schema using raw engine connection to execute scripts."""
    is_pg = engine.dialect.name == "postgresql"
    schema_file = "schema_postgres.sql" if is_pg else "schema.sql"
    schema_path = os.path.join(_ROOT, schema_file)
    
    with open(schema_path, "r") as f:
        schema = f.read()

    dbapi_conn = engine.raw_connection()
    try:
        cursor = dbapi_conn.cursor()
        if is_pg:
            for statement in _split_sql_statements(schema):
                if statement.strip():
                    cursor.execute(statement)
        else:
            cursor.executescript(schema)
        dbapi_conn.commit()
    finally:
        dbapi_conn.close()

    # Run migrations
    conn = get_db()
    try:
        from migrations.runner import run_migrations
        run_migrations(conn)
    finally:
        conn.close()


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
