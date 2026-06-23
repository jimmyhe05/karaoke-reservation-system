CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    name TEXT NOT NULL,
    google_id TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

PRAGMA foreign_keys=off;

CREATE TABLE IF NOT EXISTS reservations_new (
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

INSERT INTO reservations_new (
    id, room_id, user_id, date, start_time, end_time,
    contact_name, contact_phone, contact_email, num_people,
    language, status, total_cost, deposit_paid,
    cancellation_token, requested_at, notes, created_at, updated_at
)
SELECT 
    id, room_id, NULL, date, start_time, end_time,
    contact_name, contact_phone, contact_email, num_people,
    language, status, total_cost, deposit_paid,
    NULL, NULL, notes, created_at, updated_at
FROM reservations;

DROP TABLE reservations;

ALTER TABLE reservations_new RENAME TO reservations;

PRAGMA foreign_keys=on;
