DROP TABLE IF EXISTS reservations;
DROP TABLE IF EXISTS rooms;

CREATE TABLE rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    hourly_rate REAL NOT NULL DEFAULT 35.00,
    peak_hour_rate REAL NOT NULL DEFAULT 50.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reservations (
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
    CHECK (start_time >= '11:00' AND end_time <= '25:00'),
    CHECK (julianday(end_time) > julianday(start_time))
);

-- Insert default rooms with different capacities
INSERT INTO rooms (name, capacity, hourly_rate, peak_hour_rate) VALUES
    ('Small Room', 6, 35.00, 50.00),
    ('Medium Room', 8, 40.00, 55.00),
    ('Large Room', 12, 45.00, 60.00); 