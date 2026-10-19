from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import dashboard
from app.ai import provider as ai
from app.db import get_ai_enabled, get_connection, get_current_day, init_schema, set_state
from app.deps import get_db
from app.rules.engine import evaluate_campaign, evaluate_post

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Post-Live Watch")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def ensure_schema() -> None:
    conn = get_connection()
    try:
        init_schema(conn)
    finally:
        conn.close()


def _state(conn: sqlite3.Connection) -> dict:
    return {"current_day": get_current_day(conn), "ai_enabled": get_ai_enabled(conn), "duration_days": 7}


@app.get("/", response_class=HTMLResponse)
def overview(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    data = dashboard.get_overview(conn, st["current_day"])
    return templates.TemplateResponse("index.html", {"request": request, **st, **data})


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    cards = dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("queue.html", {"request": request, **st, "cards": cards})


@app.get("/creators", response_class=HTMLResponse)
def creators_list(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    creators = dashboard.get_creator_list(conn)
    return templates.TemplateResponse("creators.html", {"request": request, **st, "creators": creators})


@app.get("/creators/{creator_id}", response_class=HTMLResponse)
def creator_profile(request: Request, creator_id: int, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    profile = dashboard.get_creator_profile(conn, creator_id, st["current_day"])
    return templates.TemplateResponse("creator_profile.html", {"request": request, **st, **profile})


@app.get("/report", response_class=HTMLResponse)
def brand_report(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    report = dashboard.get_brand_report(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("report.html", {"request": request, **st, **report})


@app.post("/flags/{post_id}/decide", response_class=HTMLResponse)
def decide(
    request: Request,
    post_id: int,
    action: str = Form(...),
    message_text: str = Form(""),
    flag_rule_id: int = Form(0),
    conn: sqlite3.Connection = Depends(get_db),
):
    st = _state(conn)
    flag_row = conn.execute(
        "SELECT id FROM flags WHERE post_id = ? AND rule_id = ? ORDER BY id DESC LIMIT 1",
        (post_id, flag_rule_id),
    ).fetchone()

    # Persist the flag row itself for the decision log (flags are computed live by the
    # engine, not stored — but once a human acts on one, that decision IS stored).
    if flag_row is None and flag_rule_id:
        result = evaluate_post(conn, post_id, st["current_day"])
        match = next((f for f in result["flags"] if f["rule_id"] == flag_rule_id), None)
        if match is None:
            match = next((f for f in result["opportunities"] if f["rule_id"] == flag_rule_id), None)
        if match:
            cur = conn.execute(
                "INSERT INTO flags (post_id, rule_id, rule_name, severity, reason, evidence, detected_day) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (post_id, match["rule_id"], match["rule_name"], match["severity"], match["reason"],
                 str(match["evidence"]), st["current_day"]),
            )
            flag_row = {"id": cur.lastrowid}

    conn.execute(
        "INSERT INTO decisions (flag_id, post_id, action, message_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (flag_row["id"] if flag_row else None, post_id, action, message_text, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cards = dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("queue.html", {"request": request, **st, "cards": cards})


@app.get("/decisions", response_class=HTMLResponse)
def decision_log(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    rows = [
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
    return templates.TemplateResponse("decisions.html", {"request": request, **st, "rows": rows})


@app.post("/simulate/advance-day")
def advance_day(conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    new_day = min(st["current_day"] + 1, st["duration_days"])
    set_state(conn, "current_day", str(new_day))
    return RedirectResponse(url="/", status_code=303)


@app.post("/simulate/reset-day")
def reset_day(conn: sqlite3.Connection = Depends(get_db)):
    set_state(conn, "current_day", "1")
    return RedirectResponse(url="/", status_code=303)


@app.post("/settings/ai-toggle")
def toggle_ai(conn: sqlite3.Connection = Depends(get_db)):
    st = _state(conn)
    set_state(conn, "ai_enabled", "0" if st["ai_enabled"] else "1")
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/debug")
def debug(conn: sqlite3.Connection = Depends(get_db)):
    """The engine's proof-of-correctness surface — full computed state per
    post, independent of any UI. This is what 'all 12 problems trigger on
    the right posts' is verified against in tests/test_rules.py, and what a
    reviewer can hit directly without clicking through screens."""
    st = _state(conn)
    results = evaluate_campaign(conn, campaign_id=1, current_day=st["current_day"])
    return JSONResponse({**st, "results": results})
