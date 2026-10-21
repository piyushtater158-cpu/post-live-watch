"""SQLite connection + schema bootstrap. Raw sqlite3, no ORM — the data model
is small and the transparency goal (editable config, inspectable rules) is
better served by plain SQL than by an abstraction layer."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
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
        "ig_user_id TEXT",
    ],
    "decisions": [
        "source TEXT",
    ],
    "brands": [
        "ig_user_id TEXT",
    ],
    "campaigns": [
        "day_override INTEGER",
        "status TEXT NOT NULL DEFAULT 'active'",
        "metrics_provider TEXT NOT NULL DEFAULT 'seeded'",
        "created_at TEXT",
    ],
    "posts": [
        "ig_media_id TEXT",
        "last_fetched_at TEXT",
    ],
    "post_snapshots": [
        "source TEXT NOT NULL DEFAULT 'seeded'",
        "fetched_at TEXT",
    ],
}


def _migrate_table(conn: sqlite3.Connection, table: str, column_defs: list[str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column_def in column_defs:
        name = column_def.split()[0]
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


# post_snapshots.reach/saves/shares shipped NOT NULL; the public (business_discovery)
# metrics tier never returns reach, and a 0 stand-in would corrupt rules 5/12 (see
# app/schema.sql's comment on the table). SQLite's ALTER TABLE cannot drop a NOT
# NULL constraint, so an existing DB (e.g. the persisted Docker volume) needs the
# standard rebuild: create the new shape, copy rows across, swap names. Detected via
# PRAGMA table_info so this is safe — a no-op — on every future startup once it's
# run once, matching _migrate_table's idempotency discipline.
_NULLABLE_REBUILDS: dict[str, tuple[str, ...]] = {
    "post_snapshots": ("reach", "saves", "shares"),
}


def _needs_nullable_rebuild(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    info = {row["name"]: row["notnull"] for row in conn.execute(f"PRAGMA table_info({table})")}
    return any(info.get(col) == 1 for col in columns)


def _rebuild_table_nullable(conn: sqlite3.Connection, table: str) -> None:
    """Rebuilds `table` from SCHEMA_PATH's current CREATE TABLE statement (which
    already declares the target columns nullable) and copies every existing row
    across unchanged. Runs inside its own transaction with foreign keys off, so a
    mid-rebuild failure leaves the original table untouched rather than half-renamed."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        raw_schema_sql = f.read()
    # Strip '--' line comments before splitting on ';' — several of this file's
    # comments contain a literal semicolon mid-sentence, which would otherwise
    # fracture a statement across two "halves" and feed SQLite a syntax error.
    schema_sql = "\n".join(
        line for line in raw_schema_sql.splitlines() if not line.strip().startswith("--")
    )
    create_stmt = next(
        stmt.strip() + ";" for stmt in schema_sql.split(";")
        if f"CREATE TABLE IF NOT EXISTS {table} " in stmt or f"CREATE TABLE IF NOT EXISTS {table}(" in stmt
    )
    new_table = f"{table}__rebuild"
    create_new = create_stmt.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE {new_table}", 1)

    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    col_list = ", ".join(columns)

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(create_new)
        conn.execute(f"INSERT INTO {new_table} ({col_list}) SELECT {col_list} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
        # DROP TABLE drops the old table's indexes with it; re-run this table's
        # CREATE INDEX statements (IF NOT EXISTS, so safe either way) to restore them.
        for stmt in schema_sql.split(";"):
            if "CREATE INDEX IF NOT EXISTS" in stmt and f"ON {table}(" in stmt:
                conn.execute(stmt.strip() + ";")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    for table, column_defs in _TABLE_MIGRATIONS.items():
        _migrate_table(conn, table, column_defs)
    conn.commit()
    for table, columns in _NULLABLE_REBUILDS.items():
        if _needs_nullable_rebuild(conn, table, columns):
            _rebuild_table_nullable(conn, table)


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


def get_campaign_day(conn: sqlite3.Connection, campaign_id: int) -> int:
    """A campaign's current day of its own run, clamped to [1, duration_days].

    day_override set   -> simulated clock: the day simulator (app/actions.py)
                           moves this number directly; it never drifts on its own.
    day_override NULL  -> live clock: derived from wall-clock time against the
                           campaign's own start_date, the same (promised_date -
                           campaign_start).days + 1 arithmetic
                           app/rules/context.py:PostContext.due_day already uses.
                           Naive datetimes throughout, matching the rest of this
                           codebase — no timezone conversion.
    """
    row = conn.execute(
        "SELECT start_date, duration_days, day_override FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no campaign with id {campaign_id}")
    duration_days = row["duration_days"]
    if row["day_override"] is not None:
        day = row["day_override"]
    else:
        start = datetime.fromisoformat(row["start_date"])
        day = (datetime.now() - start).days + 1
    return max(1, min(day, duration_days))
