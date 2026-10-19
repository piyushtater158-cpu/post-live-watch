from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import actions, dashboard
from app.api import router as api_router
from app.db import get_connection, init_schema
from app.deps import get_db

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Post-Live Watch")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(api_router)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_CLASS = {"Act now": "act", "Needs a look": "look", "OK": "ok"}
STATUS_RANK = {"Act now": 3, "Needs a look": 2, "OK": 1}
HINT_RANK = {"yes": 3, "maybe": 2, "caution": 1}


def _hint_class(hint: str) -> str:
    if hint.startswith("Yes"):
        return "yes"
    if hint.startswith("Maybe"):
        return "maybe"
    return "caution"


templates.env.filters["status_class"] = lambda s: STATUS_CLASS.get(s, "ok")
templates.env.filters["hint_class"] = _hint_class
templates.env.filters["status_rank"] = lambda s: STATUS_RANK.get(s, 0)
templates.env.filters["hint_rank"] = lambda h: HINT_RANK[_hint_class(h)]


@app.on_event("startup")
def ensure_schema() -> None:
    conn = get_connection()
    try:
        init_schema(conn)
    finally:
        conn.close()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def overview(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    data = dashboard.get_overview(conn, st["current_day"])
    return templates.TemplateResponse("index.html", {"request": request, "active_nav": "overview", **st, **data})


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    cards = dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("queue.html", {"request": request, "active_nav": "queue", **st, "cards": cards})


@app.get("/creators", response_class=HTMLResponse)
def creators_list(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    creators = dashboard.get_creator_list(conn, st["current_day"])
    return templates.TemplateResponse("creators.html", {"request": request, "active_nav": "creators", **st, "creators": creators})


@app.get("/creators/{creator_id}", response_class=HTMLResponse)
def creator_profile(request: Request, creator_id: int, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    profile = dashboard.get_creator_profile(conn, creator_id, st["current_day"])
    return templates.TemplateResponse("creator_profile.html", {"request": request, "active_nav": "creators", **st, **profile})


@app.get("/report", response_class=HTMLResponse)
def brand_report(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    report = dashboard.get_brand_report(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("report.html", {"request": request, **st, **report})


@app.post("/flags/{post_id}/decide", response_class=HTMLResponse)
def decide(
    request: Request,
    post_id: int,
    action: str = Form(...),
    message_text: str = Form(""),
    original_message: str = Form(""),
    flag_rule_id: int = Form(0),
    conn: sqlite3.Connection = Depends(get_db),
):
    st = actions.get_app_state(conn)
    actions.record_decision(conn, post_id, action, message_text, original_message, flag_rule_id, st["current_day"])
    cards = dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("_queue_list.html", {"request": request, **st, "cards": cards})


@app.get("/decisions", response_class=HTMLResponse)
def decision_log(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    rows = actions.list_decisions(conn)
    return templates.TemplateResponse("decisions.html", {"request": request, "active_nav": "decisions", **st, "rows": rows})


@app.post("/simulate/advance-day")
def advance_day(conn: sqlite3.Connection = Depends(get_db)):
    actions.advance_day(conn)
    return RedirectResponse(url="/", status_code=303)


@app.post("/simulate/reset-day")
def reset_day(conn: sqlite3.Connection = Depends(get_db)):
    actions.reset_day(conn)
    return RedirectResponse(url="/", status_code=303)


@app.post("/settings/ai-toggle")
def toggle_ai(conn: sqlite3.Connection = Depends(get_db)):
    actions.toggle_ai(conn)
    return RedirectResponse(url="/", status_code=303)
