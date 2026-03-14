import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("crispy_sleep.db")


def _maybe_migrate_sleep_log(conn):
    """Recreate sleep_log if it has the old 'phone' column schema."""
    row = conn.execute(
        "SELECT name FROM pragma_table_info('sleep_log') WHERE name = 'phone'"
    ).fetchone()
    if row:
        conn.execute("DROP TABLE sleep_log")
        conn.execute("""
            CREATE TABLE sleep_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                event        TEXT NOT NULL CHECK(event IN ('sleep', 'wake', 'delay')),
                delay_reason TEXT,
                recorded_at  TEXT DEFAULT (datetime('now'))
            )
        """)


def init_db():
    # DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS overrides;
            DROP TABLE IF EXISTS cancellations;
            DROP TABLE IF EXISTS next_events;
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
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                event        TEXT NOT NULL CHECK(event IN ('sleep', 'wake', 'delay')),
                delay_reason TEXT,
                recorded_at  TEXT DEFAULT (datetime('now'))
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
        _maybe_migrate_sleep_log(conn)


def is_scheduling_enabled() -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'scheduling_enabled'"
        ).fetchone()
    return (row["value"] == "1") if row else True



def log_sleep_event(user_id: str, event: str, delay_reason: str | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sleep_log (user_id, event, delay_reason) VALUES (?, ?, ?)",
            (user_id, event, delay_reason),
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
