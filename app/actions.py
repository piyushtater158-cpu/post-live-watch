"""State reads and writes shared by the HTML routes (app/main.py) and the JSON
API (app/api.py), so both surfaces record decisions and move the simulator
through exactly the same code."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

from app import dashboard
from app.db import get_ai_enabled, get_campaign_day, get_connection, get_state, set_state
from app.rules.engine import evaluate_post


def list_campaigns(conn: sqlite3.Connection) -> list[dict]:
    """Every campaign, with its own derived/simulated day — the data behind the
    campaign switcher (app/campaign_intake.py's routes) and get_app_state's
    `campaigns` list."""
    rows = conn.execute(
        "SELECT camp.id, camp.name, camp.duration_days, camp.day_override, camp.status, "
        "camp.metrics_provider, b.name AS brand_name "
        "FROM campaigns camp JOIN brands b ON b.id = camp.brand_id "
        "ORDER BY camp.id"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "brand_name": r["brand_name"],
            "duration_days": r["duration_days"],
            "current_day": get_campaign_day(conn, r["id"]),
            "clock_mode": "simulated" if r["day_override"] is not None else "live",
            "status": r["status"],
            "metrics_provider": r["metrics_provider"],
        }
        for r in rows
    ]


def get_selected_campaign_id(conn: sqlite3.Connection) -> int | None:
    """The campaign the app is currently showing. Stored server-globally in
    app_state, exactly like the pre-existing current_day/ai_enabled keys —
    correct for this single-user, no-auth app, but it would need to move into a
    per-session value the moment a second concurrent user exists. Falls back to
    the lowest campaign id if nothing is selected yet, or if a stale selection
    points at a campaign that no longer exists."""
    raw = get_state(conn, "selected_campaign_id")
    if raw is not None and conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (raw,)).fetchone():
        return int(raw)
    row = conn.execute("SELECT id FROM campaigns ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def get_app_state(conn: sqlite3.Connection, campaign_id: int | None = None) -> dict:
    """campaign_id overrides the stored selection without changing it — used by
    API routes that accept an explicit ?campaign_id= rather than mutating server
    state on every read."""
    campaigns = list_campaigns(conn)
    selected_id = campaign_id if campaign_id is not None else get_selected_campaign_id(conn)
    selected = next((c for c in campaigns if c["id"] == selected_id), None)
    return {
        "campaign_id": selected["id"] if selected else None,
        "campaign_name": selected["name"] if selected else None,
        "brand_name": selected["brand_name"] if selected else None,
        "current_day": selected["current_day"] if selected else 1,
        "duration_days": selected["duration_days"] if selected else 0,
        "clock_mode": selected["clock_mode"] if selected else "simulated",
        "ai_enabled": get_ai_enabled(conn),
        "campaigns": campaigns,
    }


def select_campaign(conn: sqlite3.Connection, campaign_id: int) -> dict:
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone() is None:
        raise ValueError(f"no campaign with id {campaign_id}")
    set_state(conn, "selected_campaign_id", str(campaign_id))
    warm_ai_cache(campaign_id)
    return get_app_state(conn)


def _warm_ai_cache(campaign_id: int) -> None:
    conn = get_connection()
    try:
        st = get_app_state(conn, campaign_id)
        if st["ai_enabled"] and st["campaign_id"] is not None:
            dashboard.get_flag_queue(conn, st["campaign_id"], st["current_day"], True)
            dashboard.get_brand_report(conn, st["campaign_id"], st["current_day"], True)
    except Exception:
        pass  # warming is best-effort; the page request computes the same thing on demand
    finally:
        conn.close()


def warm_ai_cache(campaign_id: int | None = None) -> None:
    """Generates the current day's AI notes in the background so the queue and
    report pages read them from app/ai/provider.py's cache instead of waiting on
    a dozen sequential free-model calls. campaign_id=None (e.g. the app-startup
    hook in app/api.py, which has no request to read a selection from) resolves
    the currently-selected campaign at call time."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return
    if campaign_id is None:
        conn = get_connection()
        try:
            campaign_id = get_selected_campaign_id(conn)
        finally:
            conn.close()
    if campaign_id is not None:
        threading.Thread(target=_warm_ai_cache, args=(campaign_id,), daemon=True).start()


def advance_day(conn: sqlite3.Connection, campaign_id: int) -> dict:
    """Moves the SELECTED campaign's own simulated clock forward by one day.
    Only valid on a simulated-clock campaign (day_override is set) — a
    live-clock campaign's day already tracks wall-clock time and has no button
    to push; app/main.py and app/api.py disable the control in that case."""
    row = conn.execute("SELECT duration_days, day_override FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise ValueError(f"no campaign with id {campaign_id}")
    if row["day_override"] is None:
        raise ValueError("cannot advance a live-clock campaign — switch it to simulated first")
    new_day = min(row["day_override"] + 1, row["duration_days"])
    conn.execute("UPDATE campaigns SET day_override = ? WHERE id = ?", (new_day, campaign_id))
    conn.commit()
    warm_ai_cache(campaign_id)
    return get_app_state(conn, campaign_id)


def reset_day(conn: sqlite3.Connection, campaign_id: int) -> dict:
    row = conn.execute("SELECT day_override FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise ValueError(f"no campaign with id {campaign_id}")
    if row["day_override"] is None:
        raise ValueError("cannot reset a live-clock campaign — switch it to simulated first")
    conn.execute("UPDATE campaigns SET day_override = 1 WHERE id = ?", (campaign_id,))
    conn.commit()
    warm_ai_cache(campaign_id)
    return get_app_state(conn, campaign_id)


def set_clock_mode(conn: sqlite3.Connection, campaign_id: int, mode: str) -> dict:
    """Explicit switch between the two clock modes — never an implicit side
    effect of clicking Advance/Reset. 'simulated' seeds day_override from the
    campaign's currently-derived live day, so the switch doesn't jump the
    visible day; 'live' clears day_override and goes back to deriving from
    start_date (app/db.py:get_campaign_day)."""
    if mode not in ("live", "simulated"):
        raise ValueError("mode must be 'live' or 'simulated'")
    if mode == "live":
        conn.execute("UPDATE campaigns SET day_override = NULL WHERE id = ?", (campaign_id,))
    else:
        current = get_campaign_day(conn, campaign_id)
        conn.execute("UPDATE campaigns SET day_override = ? WHERE id = ?", (current, campaign_id))
    conn.commit()
    return get_app_state(conn, campaign_id)


def toggle_ai(conn: sqlite3.Connection, campaign_id: int | None = None) -> dict:
    set_state(conn, "ai_enabled", "0" if get_ai_enabled(conn) else "1")
    warm_ai_cache(campaign_id)
    return get_app_state(conn, campaign_id)


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
