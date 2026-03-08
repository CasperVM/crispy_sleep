import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("crispy_sleep.db")


def init_db():
    # DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS overrides (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type       TEXT NOT NULL,
                trigger_at       TEXT NOT NULL,
                duration_minutes INTEGER,
                ctype            INTEGER,
                status           TEXT DEFAULT 'pending',
                created_at       TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS cancellations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type   TEXT,
                cancel_date  TEXT NOT NULL,
                created_at   TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS gcal_cache (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                gcal_id          TEXT UNIQUE NOT NULL,
                event_type       TEXT NOT NULL,
                trigger_at       TEXT NOT NULL,
                duration_minutes INTEGER,
                ctype            INTEGER,
                updated_at       TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sleep_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phone       TEXT NOT NULL,
                event       TEXT NOT NULL CHECK(event IN ('sleep', 'wake')),
                recorded_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS next_events (
                event_type TEXT PRIMARY KEY,
                trigger_at TEXT,
                source     TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sensor_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                temperature REAL,
                humidity    REAL,
                lux         REAL,
                lux_avg     REAL,
                sound       REAL,
                sound_avg   REAL,
                recorded_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_log_recorded_at
                ON sensor_log (recorded_at);
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES ('scheduling_enabled', '1');
        """)


def is_scheduling_enabled() -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'scheduling_enabled'"
        ).fetchone()
    return (row["value"] == "1") if row else True


def cancel_todays_events():
    """Cancel all scheduled events for today - called on any manual light intervention.

    NOTE: note actually in use, this is a bit extreme...
    """
    from datetime import datetime

    today = datetime.now().date().isoformat()
    with get_conn() as conn:
        for etype in ("winddown", "sunrise"):
            conn.execute(
                "INSERT OR IGNORE INTO cancellations (event_type, cancel_date) VALUES (?, ?)",
                (etype, today),
            )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
