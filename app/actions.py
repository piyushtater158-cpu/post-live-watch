"""State reads and writes shared by the HTML routes (app/main.py) and the JSON
API (app/api.py), so both surfaces record decisions and move the simulator
through exactly the same code."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.db import get_ai_enabled, get_current_day, set_state
from app.rules.engine import evaluate_post

DURATION_DAYS = 7


def get_app_state(conn: sqlite3.Connection) -> dict:
    return {"current_day": get_current_day(conn), "ai_enabled": get_ai_enabled(conn), "duration_days": DURATION_DAYS}


def advance_day(conn: sqlite3.Connection) -> dict:
    st = get_app_state(conn)
    set_state(conn, "current_day", str(min(st["current_day"] + 1, st["duration_days"])))
    return get_app_state(conn)


def reset_day(conn: sqlite3.Connection) -> dict:
    set_state(conn, "current_day", "1")
    return get_app_state(conn)


def toggle_ai(conn: sqlite3.Connection) -> dict:
    set_state(conn, "ai_enabled", "0" if get_ai_enabled(conn) else "1")
    return get_app_state(conn)


def record_decision(
    conn: sqlite3.Connection,
    post_id: int,
    action: str,
    message_text: str,
    original_message: str,
    flag_rule_id: int,
    current_day: int,
) -> None:
    flag_row = conn.execute(
        "SELECT id FROM flags WHERE post_id = ? AND rule_id = ? ORDER BY id DESC LIMIT 1",
        (post_id, flag_rule_id),
    ).fetchone()

    # Persist the flag row itself for the decision log (flags are computed live by the
    # engine, not stored — but once a human acts on one, that decision IS stored).
    if flag_row is None and flag_rule_id:
        result = evaluate_post(conn, post_id, current_day)
        match = next((f for f in result["flags"] if f["rule_id"] == flag_rule_id), None)
        if match is None:
            match = next((f for f in result["opportunities"] if f["rule_id"] == flag_rule_id), None)
        if match:
            cur = conn.execute(
                "INSERT INTO flags (post_id, rule_id, rule_name, severity, reason, evidence, detected_day) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (post_id, match["rule_id"], match["rule_name"], match["severity"], match["reason"],
                 str(match["evidence"]), current_day),
            )
            flag_row = {"id": cur.lastrowid}

    # approve = the suggestion exactly as written (original_message); edit = whatever the
    # AM actually typed (message_text); dismiss = no message at all.
    if action == "approve":
        stored_message = original_message
    elif action == "edit":
        stored_message = message_text
    else:
        stored_message = None

    conn.execute(
        "INSERT INTO decisions (flag_id, post_id, action, message_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (flag_row["id"] if flag_row else None, post_id, action, stored_message, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def list_decisions(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT dec.*, c.handle, f.rule_name "
            "FROM decisions dec "
            "JOIN posts p ON p.id = dec.post_id "
            "JOIN deliverables d ON d.id = p.deliverable_id "
            "JOIN creators c ON c.id = d.creator_id "
            "LEFT JOIN flags f ON f.id = dec.flag_id "
            "ORDER BY dec.created_at DESC"
        ).fetchall()
    ]
