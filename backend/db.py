"""SQLite database initialization, password hashing (bcrypt), and token generation."""

import hashlib
import logging
import os
import sqlite3
from pathlib import Path

import bcrypt

from config import DATA_DIR

log = logging.getLogger(__name__)
DB_PATH = DATA_DIR / "users.db"

# Legacy salt for SHA-256 migration
_LEGACY_SALT = "dd_report_gen_salt_2024"


def _legacy_hash(password: str) -> str:
    """SHA-256 hash with fixed salt (legacy, for migration only)."""
    return hashlib.sha256((_LEGACY_SALT + password).encode()).hexdigest()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def verify_password_with_migration(password: str, stored_hash: str, user_id: int) -> bool:
    """Verify password, auto-migrating legacy SHA-256 hashes to bcrypt.

    If the stored hash is a legacy SHA-256 hash and the password matches,
    the hash is upgraded to bcrypt in-place.
    """
    # Try bcrypt first
    if verify_password(password, stored_hash):
        return True
    # Try legacy SHA-256
    if stored_hash == _legacy_hash(password):
        # Migrate to bcrypt
        new_hash = hash_password(password)
        conn = get_db()
        try:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.commit()
        finally:
            conn.close()
        return True
    return False


def generate_token() -> str:
    """Generate a random 32-character hex token."""
    return os.urandom(16).hex()


def get_db() -> sqlite3.Connection:
    """Return a connection with Row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables and seed the default admin account."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS upload_sessions (
            session_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            bd_code TEXT,
            company_name TEXT,
            project_name TEXT,
            industry TEXT,
            province TEXT,
            city TEXT,
            district TEXT,
            is_listed TEXT,
            stock_code TEXT,
            website TEXT,
            revenue TEXT,
            net_profit TEXT,
            revenue_yuan TEXT,
            net_profit_yuan TEXT,
            valuation_yuan TEXT,
            valuation_date TEXT,
            description TEXT,
            company_intro TEXT,
            industry_tags TEXT,
            referral_status TEXT,
            is_traded TEXT,
            dept_primary TEXT,
            dept_owner TEXT,
            annual_report_attachment TEXT,
            remarks TEXT,
            score REAL,
            rating TEXT,
            manual_rating TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            owner TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            file_size INTEGER,
            intro_attachment TEXT,
            metadata_json TEXT,
            locked_fields TEXT,
            push_records TEXT,
            attachments TEXT,
            md_path TEXT,
            chunks_path TEXT,
            debug_dir TEXT,
            attachments_dir TEXT,
            token_usage_json TEXT,
            estimated_cost REAL
        );
        CREATE INDEX IF NOT EXISTS idx_reports_bd_code ON reports(bd_code);
        CREATE INDEX IF NOT EXISTS idx_reports_company_name ON reports(company_name);
        CREATE INDEX IF NOT EXISTS idx_reports_owner ON reports(owner);
        CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
        CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reports_rating ON reports(rating);
        CREATE TABLE IF NOT EXISTS report_versions (
            version_id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            created_by TEXT,
            reason TEXT,
            FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_versions_report_id ON report_versions(report_id);
        CREATE INDEX IF NOT EXISTS idx_versions_created_at ON report_versions(created_at DESC);
    """)
    # Seed admin if not exists
    row = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", 1),
        )

    # Migration: Add token tracking columns if they don't exist
    try:
        cursor = conn.cursor()
        # Check if columns exist
        cursor.execute("PRAGMA table_info(reports)")
        columns = {row[1] for row in cursor.fetchall()}

        if "token_usage_json" not in columns:
            cursor.execute("ALTER TABLE reports ADD COLUMN token_usage_json TEXT")
            log.info("Added token_usage_json column to reports table")

        if "estimated_cost" not in columns:
            cursor.execute("ALTER TABLE reports ADD COLUMN estimated_cost REAL")
            log.info("Added estimated_cost column to reports table")

        conn.commit()
    except Exception as e:
        log.warning(f"Migration warning: {e}")

    conn.commit()
    conn.close()


def get_next_bd_code() -> str:
    """Generate next bd_code in format BD00001, BD00002, etc.

    Thread-safe atomic increment using SQLite transaction.
    """
    conn = get_db()
    try:
        # Get current sequence number
        row = conn.execute("SELECT value FROM settings WHERE key = 'bd_code_seq'").fetchone()
        if row:
            seq = int(row["value"]) + 1
        else:
            seq = 1

        # Update sequence
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('bd_code_seq', ?)",
            (str(seq),)
        )
        conn.commit()

        # Format as BD00001
        return f"BD{seq:05d}"
    finally:
        conn.close()
