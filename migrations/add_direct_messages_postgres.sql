-- Migration: Add direct messages table for PostgreSQL
CREATE TABLE IF NOT EXISTS direct_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    session_id VARCHAR(255) NOT NULL,
    guest_name VARCHAR(255),
    guest_email VARCHAR(255),
    message TEXT NOT NULL,
    sender_role VARCHAR(50) NOT NULL CHECK(sender_role IN ('customer', 'staff', 'guest')),
    read_by_staff INTEGER DEFAULT 0,
    read_by_user INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_direct_messages_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_direct_messages_session ON direct_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_direct_messages_user ON direct_messages(user_id);
