-- Only drop tables if we're explicitly recreating the database
-- DROP TABLE IF EXISTS reservations;
-- DROP TABLE IF EXISTS rooms;
-- DROP TABLE IF EXISTS idle_reservations;

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
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_phone TEXT NOT NULL,
    contact_email TEXT,
    num_people INTEGER NOT NULL,
    language TEXT DEFAULT 'en',
    status TEXT CHECK(status IN ('confirmed', 'cancelled', 'completed', 'no_show')) DEFAULT 'confirmed',
    total_cost REAL NOT NULL,
    deposit_paid REAL DEFAULT 0.00,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id),
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
INSERT INTO rooms (id, name, capacity, hourly_rate, peak_hour_rate)
SELECT 0, 'Idle', 999, 0.00, 0.00
WHERE NOT EXISTS (SELECT 1 FROM rooms WHERE id = 0);

-- Create table for idle reservations
CREATE TABLE IF NOT EXISTS idle_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id)
);