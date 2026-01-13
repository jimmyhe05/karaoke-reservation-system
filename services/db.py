import sqlite3
from flask import g, current_app


def get_db():
    """Get a database connection bound to the Flask app context."""
    if 'db' not in g:
        db_path = current_app.config.get('DATABASE')
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON;')
        g.db.execute('PRAGMA journal_mode = WAL;')
    return g.db


def close_db(error=None):
    """Close the database connection if present."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize the database schema and indexes (idempotent)."""
    db = get_db()
    with current_app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()
