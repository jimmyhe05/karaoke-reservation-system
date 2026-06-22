#!/bin/bash
# Backup SQLite Database safely using the .backup command

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Prioritize DATABASE env variable if set
if [ -z "$DATABASE" ]; then
    DB_FILE="$ROOT_DIR/karaoke.db"
else
    DB_FILE="$DATABASE"
fi

BACKUP_DIR="$ROOT_DIR/backups"

# Check if sqlite3 is installed
if ! command -v sqlite3 &> /dev/null; then
    echo "Error: sqlite3 command not found. Cannot perform backup."
    exit 1
fi

if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file $DB_FILE does not exist."
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/karaoke_backup_$TIMESTAMP.db"

echo "Creating safe backup of $DB_FILE..."
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ]; then
    echo "Backup successful: $BACKUP_FILE"
    # Compress the backup
    tar -czf "$BACKUP_FILE.tar.gz" -C "$BACKUP_DIR" "$(basename "$BACKUP_FILE")"
    rm "$BACKUP_FILE"
    echo "Compressed to: $BACKUP_FILE.tar.gz"
else
    echo "Backup failed!"
    exit 1
fi
