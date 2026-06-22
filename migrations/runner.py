import os
import logging
from flask import current_app
from services.db import is_postgres_connection, _split_sql_statements

logger = logging.getLogger(__name__)

def run_migrations(db):
    """Run all unapplied SQL migrations in the migrations/ directory."""
    
    # 1. Create schema_migrations table if it doesn't exist
    if is_postgres_connection(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        db.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    db.commit()

    # 2. Check if this is an existing database upgrading to the migration system
    # If schema_migrations is empty, but reservations exists, we mark existing
    # migrations as applied to prevent re-running manual migrations.
    migrations_dir = os.path.dirname(__file__)
    migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])
    
    applied_count = db.execute('SELECT COUNT(*) as c FROM schema_migrations').fetchone()['c']
    if applied_count == 0:
        # Check if reservations table exists
        if is_postgres_connection(db):
            has_reservations = db.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'reservations'").fetchone() is not None
        else:
            has_reservations = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reservations'").fetchone() is not None
        
        if has_reservations:
            logger.info("Existing database detected. Marking existing migrations as applied.")
            for filename in migration_files:
                db.execute('INSERT INTO schema_migrations (filename) VALUES (?)', (filename,))
            db.commit()
            return

    # 3. Apply new migrations
    for filename in migration_files:
        row = db.execute('SELECT filename FROM schema_migrations WHERE filename = ?', (filename,)).fetchone()
        if row:
            continue
        
        logger.info(f"Applying migration: {filename}")
        filepath = os.path.join(migrations_dir, filename)
        with open(filepath, 'r') as f:
            sql = f.read()

        try:
            if is_postgres_connection(db):
                for statement in _split_sql_statements(sql):
                    db.execute(statement)
            else:
                db.cursor().executescript(sql)
            
            db.execute('INSERT INTO schema_migrations (filename) VALUES (?)', (filename,))
            db.commit()
            logger.info(f"Successfully applied {filename}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to apply migration {filename}: {e}")
            raise
