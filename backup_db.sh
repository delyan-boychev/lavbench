#!/bin/bash

# Database Backup script for NAI Competition Platform
# Can be run manually or added to crontab:
# Example (Every day at midnight): 0 0 * * * /Users/delyan-boychev/nai-webplatform/backup_db.sh

echo "============================================="
echo "   Database Backup Tool - NAI Competition"
echo "============================================="

# Create backup directory
BACKUP_DIR="/Users/delyan-boychev/nai-webplatform/backups"
mkdir -p "$BACKUP_DIR"

# Read DATABASE_URL or fallback to local SQLite
DB_URL=${DATABASE_URL:-"sqlite"}

if [[ "$DB_URL" == *"postgresql://"* ]] || [[ "$DB_URL" == *"postgres://"* ]]; then
    echo "--> Detected PostgreSQL database. Parsing credentials..."
    
    # Extract details using python regex
    PYTHON_CMD="import urllib.parse, sys; p = urllib.parse.urlparse(sys.argv[1]); print(f'{p.username},{p.password},{p.hostname},{p.port or 5432},{p.path.lstrip(\"/ \")}')"
    CREDENTIALS=$(python3 -c "$PYTHON_CMD" "$DB_URL")
    
    IFS=',' read -r USER PWD HOST PORT DBNAME <<< "$CREDENTIALS"
    
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/backup_${DBNAME}_${TIMESTAMP}.sql.gz"
    
    echo "    Host: $HOST"
    echo "    Port: $PORT"
    echo "    Database: $DBNAME"
    echo "    Target: $BACKUP_FILE"
    
    # Run pg_dump
    export PGPASSWORD="$PWD"
    pg_dump -h "$HOST" -p "$PORT" -U "$USER" -d "$DBNAME" | gzip > "$BACKUP_FILE"
    
    if [ $? -eq 0 ]; then
        echo "    [SUCCESS] PostgreSQL backup completed."
    else
        echo "    [ERROR] PostgreSQL backup failed."
        exit 1
    fi
else
    echo "--> Detected SQLite database. Backing up SQLite file..."
    
    SQLITE_PATH="/Users/delyan-boychev/nai-webplatform/backend/nai_competition.db"
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/backup_sqlite_${TIMESTAMP}.db.gz"
    
    if [ -f "$SQLITE_PATH" ]; then
        gzip -c "$SQLITE_PATH" > "$BACKUP_FILE"
        echo "    [SUCCESS] SQLite backup completed."
        echo "    Target: $BACKUP_FILE"
    else
        echo "    [ERROR] SQLite database file not found at $SQLITE_PATH."
        exit 1
    fi
fi

# Encrypt the backup file at rest using AES-256-CBC
KEY_PASS=${SECRET_KEY:-"nai-super-secret-key-1337"}
ENCRYPTED_FILE="${BACKUP_FILE}.enc"

echo "--> Encrypting backup file at rest using AES-256-CBC..."
openssl enc -aes-256-cbc -salt -pbkdf2 -pass pass:"$KEY_PASS" -in "$BACKUP_FILE" -out "$ENCRYPTED_FILE"

if [ $? -eq 0 ]; then
    echo "    [SUCCESS] Backup encrypted successfully: $ENCRYPTED_FILE"
    rm "$BACKUP_FILE"
else
    echo "    [WARNING] Failed to encrypt backup file. Leaving plaintext backup."
fi

# Clean up backups older than 30 days
echo "--> Cleaning up old backups..."
find "$BACKUP_DIR" -type f -mtime +30 -name "backup_*" -delete
echo "    Cleanup finished. Keeping last 30 days of database states."
echo "============================================="
