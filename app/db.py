"""SQLite connection + schema bootstrap. Raw sqlite3, no ORM — the data model
is small and the transparency goal (editable config, inspectable rules) is
better served by plain SQL than by an abstraction layer."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("POST_LIVE_WATCH_DB", Path(__file__).resolve().parent.parent / "data" / "postlivewatch.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to a table after the initial schema shipped. schema.sql uses
# CREATE TABLE IF NOT EXISTS, so an existing DB (e.g. the persisted Docker
# volume) would never pick these up without this guarded migration — it reads
# the live column list per table and ALTERs in only what's missing. Idempotent,
# no version table; safe to call on every startup.
_TABLE_MIGRATIONS: dict[str, list[str]] = {
    "deliverables": [
        "required_disclosure TEXT",
        "required_tag TEXT",
        "required_hashtag TEXT",
        "requires_link_sticker INTEGER",
        "deal_type TEXT NOT NULL DEFAULT 'paid'",
        "barter_value REAL",
        "bonus_threshold INTEGER",
        "bonus_amount REAL",
        "waived_notes TEXT",
    ],
    "creators": [
        "metrics_source TEXT",
    ],
    "decisions": [
        "source TEXT",
    ],
}


def _migrate_table(conn: sqlite3.Connection, table: str, column_defs: list[str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column_def in column_defs:
        name = column_def.split()[0]
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def init_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    for table, column_defs in _TABLE_MIGRATIONS.items():
        _migrate_table(conn, table, column_defs)
    conn.commit()


def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_current_day(conn: sqlite3.Connection) -> int:
    return int(get_state(conn, "current_day", "1"))


def get_ai_enabled(conn: sqlite3.Connection) -> bool:
    return get_state(conn, "ai_enabled", "1") == "1"
