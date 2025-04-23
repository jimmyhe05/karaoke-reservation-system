-- Add language column to reservations table
ALTER TABLE reservations ADD COLUMN language TEXT DEFAULT 'en'; 