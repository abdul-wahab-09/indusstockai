"""SQLite access layer: connection handling, schema creation and safe migrations."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DB_PATH

BASE_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS spare_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_name TEXT,
        category TEXT,
        part_number TEXT,
        quantity INTEGER,
        min_stock INTEGER,
        location TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_id INTEGER,
        transaction_type TEXT,
        quantity INTEGER,
        transaction_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'user',
        password_hash TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        last_login TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        code_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        used INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reset_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        user_id INTEGER,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        resolved_by TEXT,
        resolved_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_time TEXT DEFAULT CURRENT_TIMESTAMP,
        actor TEXT,
        action TEXT,
        entity TEXT,
        entity_id INTEGER,
        details TEXT
    )
    """,
]

# Columns added in v2. Existing databases are upgraded in place; no data is lost.
PART_COLUMNS = {
    "manufacturer": "TEXT",
    "unit": "TEXT DEFAULT 'pcs'",
    "remarks": "TEXT",
    "is_active": "INTEGER DEFAULT 1",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
TRANSACTION_COLUMNS = {"reference": "TEXT", "remarks": "TEXT", "performed_by": "TEXT"}
USER_COLUMNS = {"email": "TEXT", "recovery_hash": "TEXT", "recovery_created_at": "TEXT",
                "password_changed_at": "TEXT"}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_parts_number ON spare_parts(part_number)",
    "CREATE INDEX IF NOT EXISTS idx_parts_category ON spare_parts(category)",
    "CREATE INDEX IF NOT EXISTS idx_tx_part ON transactions(part_id)",
    "CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(transaction_date)",
    "CREATE INDEX IF NOT EXISTS idx_resets_user ON password_resets(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_requests_status ON reset_requests(status)",
]


def connect(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_connection(db_path: str | os.PathLike | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_audit(conn: sqlite3.Connection, actor: str, action: str, entity: str,
                entity_id: int | None, details: str) -> None:
    """Append an entry to the audit trail (UTC timestamp)."""
    from datetime import datetime, timezone

    conn.execute(
        "INSERT INTO audit_log (event_time, actor, action, entity, entity_id, details) VALUES (?,?,?,?,?,?)",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), actor or "system", action, entity,
         entity_id, details),
    )


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db(db_path: str | os.PathLike | None = None) -> None:
    """Create tables, upgrade older databases and tidy legacy values."""
    with get_connection(db_path) as conn:
        for statement in BASE_SCHEMA:
            conn.execute(statement)

        for table, columns in (("spare_parts", PART_COLUMNS), ("transactions", TRANSACTION_COLUMNS),
                               ("users", USER_COLUMNS)):
            present = _existing_columns(conn, table)
            for name, definition in columns.items():
                if name not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

        conn.execute("UPDATE spare_parts SET is_active = 1 WHERE is_active IS NULL")
        conn.execute("UPDATE spare_parts SET unit = 'pcs' WHERE unit IS NULL OR TRIM(unit) = ''")
        conn.execute("UPDATE spare_parts SET quantity = 0 WHERE quantity IS NULL")
        conn.execute("UPDATE spare_parts SET min_stock = 0 WHERE min_stock IS NULL")
        # Legacy rows may contain stray tabs/spaces (e.g. "\tLC1D25"), which break searching.
        conn.execute(
            """
            UPDATE spare_parts SET
                part_name   = TRIM(part_name,   ' ' || char(9) || char(10) || char(13)),
                part_number = TRIM(part_number, ' ' || char(9) || char(10) || char(13)),
                location    = TRIM(location,    ' ' || char(9) || char(10) || char(13))
            """
        )
        for statement in INDEXES:
            conn.execute(statement)


def backup_bytes(db_path: str | os.PathLike | None = None) -> bytes:
    """Return a consistent copy of the database file (safe while the app is running)."""
    source = connect(db_path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        target = sqlite3.connect(tmp_path)
        try:
            source.backup(target)
        finally:
            target.close()
        return Path(tmp_path).read_bytes()
    finally:
        source.close()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
