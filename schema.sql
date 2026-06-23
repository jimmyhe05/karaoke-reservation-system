-- Only drop tables if we're explicitly recreating the database
-- DROP TABLE IF EXISTS reservations;
-- DROP TABLE IF EXISTS rooms;
-- DROP TABLE IF EXISTS idle_reservations;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    name TEXT NOT NULL,
    google_id TEXT UNIQUE,
    email_notifications INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    hourly_rate REAL NOT NULL DEFAULT 35.00,
    peak_hour_rate REAL NOT NULL DEFAULT 50.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    user_id INTEGER,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_phone TEXT NOT NULL,
    contact_email TEXT,
    num_people INTEGER NOT NULL,
    language TEXT DEFAULT 'en',
    status TEXT CHECK(status IN ('confirmed', 'cancelled', 'completed', 'no_show', 'pending', 'rejected')) DEFAULT 'confirmed',
    total_cost REAL NOT NULL,
    deposit_paid REAL DEFAULT 0.00,
    cancellation_token TEXT UNIQUE DEFAULT NULL,
    requested_at TIMESTAMP DEFAULT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CHECK (num_people > 0),
    CHECK (start_time >= '11:00' AND (end_time <= '25:00' OR end_time <= '01:00'))
);

-- Only insert default rooms if the table is empty
INSERT INTO rooms (name, capacity, hourly_rate, peak_hour_rate)
SELECT 'Room 1', 8, 35.00, 50.00
WHERE NOT EXISTS (SELECT 1 FROM rooms WHERE id = 1);

INSERT INTO rooms (name, capacity, hourly_rate, peak_hour_rate)
SELECT 'Room 2', 8, 35.00, 50.00
WHERE NOT EXISTS (SELECT 1 FROM rooms WHERE id = 2);

INSERT INTO rooms (name, capacity, hourly_rate, peak_hour_rate)
SELECT 'Room 3', 8, 35.00, 50.00
WHERE NOT EXISTS (SELECT 1 FROM rooms WHERE id = 3);

-- Create a special "idle" room with ID 0
-- Create table for idle reservations
CREATE TABLE IF NOT EXISTS idle_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id)
);

-- Audit log for admin actions and API activity
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    role TEXT NOT NULL,
    path TEXT,
    method TEXT,
    request_id TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reservation history snapshots for traceability
CREATE TABLE IF NOT EXISTS reservation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reservation_id INTEGER,
    message TEXT NOT NULL,
    read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE SET NULL
);

-- Helpful indexes for common queries
CREATE INDEX IF NOT EXISTS idx_reservations_room_date ON reservations(room_id, date);
CREATE INDEX IF NOT EXISTS idx_reservations_date_status ON reservations(date, status);
CREATE INDEX IF NOT EXISTS idx_idle_reservations_date_res ON idle_reservations(date, reservation_id);

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
CREATE INDEX IF NOT EXISTS idx_audit_log_action_time ON audit_log(action, created_at);
CREATE INDEX IF NOT EXISTS idx_reservation_history_res ON reservation_history(reservation_id, created_at);