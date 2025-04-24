-- Drop the old constraint and add a new one that handles overnight reservations
PRAGMA foreign_keys=off;

-- Create a temporary table with the new schema
CREATE TABLE reservations_new (
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

-- Copy data from the old table to the new one
INSERT INTO reservations_new 
SELECT * FROM reservations;

-- Drop the old table
DROP TABLE reservations;

-- Rename the new table to the original name
ALTER TABLE reservations_new RENAME TO reservations;

PRAGMA foreign_keys=on;
