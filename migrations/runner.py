import os
import logging

logger = logging.getLogger(__name__)


def _is_postgres(db):
    """Detect Postgres by checking the wrapper attribute set in services/db.py."""
    return getattr(db, "is_postgres", False)


def _split_statements(script):
    """Split a SQL script into individual statements, ignoring comments."""
    statements = []
    current = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return [s for s in statements if s.strip()]


def run_migrations(db):
    """Run all unapplied SQL migrations in the migrations/ directory."""

    # 1. Create schema_migrations table if it doesn't exist
    if _is_postgres(db):
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
    else:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
    db.commit()

    # 2. If schema_migrations is empty but reservations already exists,
    #    this is an existing database being upgraded — mark all known
    #    migrations as applied so we don't re-run them.
    migrations_dir = os.path.dirname(__file__)
    is_pg = _is_postgres(db)
    migration_files = sorted(
        [
            f for f in os.listdir(migrations_dir)
            if f.endswith(".sql")
            and (not f.endswith("_postgres.sql") if not is_pg else not f.endswith("_sqlite.sql"))
        ]
    )

    applied_count = db.execute(
        "SELECT COUNT(*) as c FROM schema_migrations"
    ).fetchone()["c"]
    if applied_count == 0:
        if _is_postgres(db):
            has_reservations = (
                db.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'reservations'"
                ).fetchone()
                is not None
            )
        else:
            has_reservations = (
                db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='reservations'"
                ).fetchone()
                is not None
            )

        if has_reservations:
            logger.info(
                "Existing database detected. Marking existing migrations as applied."
            )
            for filename in migration_files:
                db.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (?)", (filename,)
                )
            db.commit()
            return

    # 3. Apply new migrations
    for filename in migration_files:
        row = db.execute(
            "SELECT filename FROM schema_migrations WHERE filename = ?", (filename,)
        ).fetchone()
        if row:
            continue

        logger.info(f"Applying migration: {filename}")
        filepath = os.path.join(migrations_dir, filename)
        with open(filepath, "r") as f:
            sql = f.read()

        try:
            if _is_postgres(db):
                for statement in _split_statements(sql):
                    db.execute(statement)
            else:
                db.cursor().executescript(sql)

            db.execute(
                "INSERT INTO schema_migrations (filename) VALUES (?)", (filename,)
            )
            db.commit()
            logger.info(f"Successfully applied {filename}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to apply migration {filename}: {e}")
            raise
