-- Migration: Add direct messages table for SQLite
CREATE TABLE IF NOT EXISTS direct_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    session_id TEXT NOT NULL,
    guest_name TEXT,
    guest_email TEXT,
    message TEXT NOT NULL,
    sender_role TEXT CHECK(sender_role IN ('customer', 'staff', 'guest')) NOT NULL,
    read_by_staff INTEGER DEFAULT 0,
    read_by_user INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_direct_messages_session ON direct_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_direct_messages_user ON direct_messages(user_id);
