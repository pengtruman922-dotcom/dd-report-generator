"""SQLite database initialization, password hashing, and token generation."""

import hashlib
import os
import sqlite3
from pathlib import Path

from config import DATA_DIR

DB_PATH = DATA_DIR / "users.db"

_SALT = "dd_report_gen_salt_2024"


def hash_password(password: str) -> str:
    """SHA-256 hash with fixed salt."""
    return hashlib.sha256((_SALT + password).encode()).hexdigest()


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
    """)
    # Seed admin if not exists
    row = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", 1),
        )
    conn.commit()
    conn.close()
