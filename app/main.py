from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import actions, dashboard, intake
from app.ai import provider as ai
from app.api import router as api_router
from app.config import load_thresholds
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
    if hint.startswith(("Maybe", "New")):
        return "maybe"
    return "caution"


templates.env.filters["status_class"] = lambda s: STATUS_CLASS.get(s, "ok")
templates.env.filters["hint_class"] = _hint_class
# Plain Jinja2 (unlike Flask) has no tojson filter built in — needed to round-trip
# the intake draft through a hidden field (app/templates/_intake_preview.html).
# Autoescaping on .html templates still applies to the filter's output, so this
# stays safe inside an HTML attribute.
templates.env.filters["tojson"] = json.dumps
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


# ---------------------------------------------------------------------------
# Deal intake — turns an AM's free-text brief into real creators/deliverables/
# posts rows, with AI (or its deterministic fallback) only ever drafting and a
# human always confirming. See app/intake.py's module docstring for why that
# approval step is mandatory rather than a nice-to-have.
# ---------------------------------------------------------------------------


def _render_preview(request: Request, conn: sqlite3.Connection, draft: dict, blocking_errors: list[dict],
                     result: dict | None = None) -> HTMLResponse:
    st = actions.get_app_state(conn)
    campaign_row = intake.campaign_row(conn)
    draft = intake.attach_preview_notes(draft, campaign_row)
    package = dashboard.get_creator_package(conn, result["creator_id"], st["current_day"]) if result else None
    return templates.TemplateResponse("_intake_preview.html", {
        "request": request, **st, "draft": draft, "blocking_errors": blocking_errors,
        "result": result, "package": package, "campaign": campaign_row,
    })


@app.get("/intake", response_class=HTMLResponse)
def intake_form(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return templates.TemplateResponse("intake.html", {
        "request": request, "active_nav": "intake", **st, "campaign": intake.campaign_row(conn),
    })


@app.post("/intake/parse", response_class=HTMLResponse)
def intake_parse(request: Request, brief_text: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    campaign_row = intake.campaign_row(conn)
    thresholds = load_thresholds()
    raw = ai.parse_deal_brief(
        st["ai_enabled"], brief_text, campaign_row, st["current_day"], campaign_row["duration_days"],
        intake.known_handles(conn),
    )
    draft = intake.normalize_draft(conn, raw, campaign_row, st["current_day"], thresholds)
    errors = intake.validate_draft(draft, campaign_row, thresholds)
    return _render_preview(request, conn, draft, [e for e in errors if e["blocking"]])


@app.post("/intake/confirm", response_class=HTMLResponse)
def intake_confirm(
    request: Request,
    action: str = Form(...),
    brief_text: str = Form(""),
    original_draft: str = Form(""),
    source: str = Form("template"),
    creator_handle: str = Form(""),
    creator_existing_id: str = Form(""),
    creator_followers: str = Form(""),
    creator_tier: str = Form(""),
    creator_niche: str = Form(""),
    creator_avg_reach: str = Form(""),
    creator_avg_engagement_rate: str = Form(""),
    d_format: list[str] = Form([]),
    d_deal_type: list[str] = Form([]),
    d_fee: list[str] = Form([]),
    d_barter_value: list[str] = Form([]),
    d_bonus_threshold: list[str] = Form([]),
    d_bonus_amount: list[str] = Form([]),
    d_reach_mode: list[str] = Form([]),
    d_min_reach: list[str] = Form([]),
    d_due_day: list[str] = Form([]),
    d_tag_mode: list[str] = Form([]),
    d_tag_value: list[str] = Form([]),
    d_tag_reason: list[str] = Form([]),
    d_hashtag_mode: list[str] = Form([]),
    d_hashtag_value: list[str] = Form([]),
    d_hashtag_reason: list[str] = Form([]),
    d_link_mode: list[str] = Form([]),
    conn: sqlite3.Connection = Depends(get_db),
):
    st = actions.get_app_state(conn)
    campaign_row = intake.campaign_row(conn)
    thresholds = load_thresholds()

    if action == "dismiss":
        return _render_preview(request, conn, {
            "source": source, "brief_text": brief_text,
            "creator": {"handle": "", "existing_creator_id": None, "existing_suggestions": [],
                        "followers": None, "tier": "micro", "niche": "", "avg_reach": 0.0,
                        "avg_engagement_rate": 0.0, "metrics_source": "estimated"},
            "deliverables": [], "warnings": [], "errors": [],
        }, [])

    if action == "approve":
        # Exactly like /flags/{id}/decide's approve: store the draft the AI (or
        # fallback) actually produced, verbatim — never the (identical, since
        # nothing was changed) values re-typed out of the form.
        raw = json.loads(original_draft) if original_draft else {}
        raw.setdefault("source", source)
        raw.setdefault("brief_text", brief_text)
    else:  # edit — rebuilt from whatever the AM actually typed
        def _blank_none(v: str) -> str | None:
            return v if v.strip() != "" else None

        def _at(lst: list[str], i: int, default: str = "") -> str:
            return lst[i] if i < len(lst) else default

        raw_creator = {
            "handle": creator_handle,
            "existing_creator_id": int(creator_existing_id) if creator_existing_id else None,
            "followers": _blank_none(creator_followers),
            "tier": creator_tier or None,
            "niche": creator_niche,
            "avg_reach": _blank_none(creator_avg_reach),
            "avg_engagement_rate": _blank_none(creator_avg_engagement_rate),
        }

        raw_deliverables = []
        for i in range(len(d_format)):
            tag_mode = d_tag_mode[i] if i < len(d_tag_mode) else "inherit"
            hashtag_mode = d_hashtag_mode[i] if i < len(d_hashtag_mode) else "inherit"
            link_mode = d_link_mode[i] if i < len(d_link_mode) else "inherit"
            reach_mode = d_reach_mode[i] if i < len(d_reach_mode) else "guarantee"

            waived_notes = {}
            required_tag = None if tag_mode == "inherit" else (_at(d_tag_value, i) if tag_mode == "literal" else "")
            if tag_mode == "waived" and _at(d_tag_reason, i).strip():
                waived_notes["required_tag"] = _at(d_tag_reason, i).strip()
            required_hashtag = None if hashtag_mode == "inherit" else (_at(d_hashtag_value, i) if hashtag_mode == "literal" else "")
            if hashtag_mode == "waived" and _at(d_hashtag_reason, i).strip():
                waived_notes["required_hashtag"] = _at(d_hashtag_reason, i).strip()
            requires_link_sticker = {"inherit": None, "required": True, "waived": False}.get(link_mode)

            raw_deliverables.append({
                "format": _at(d_format, i) or None,
                "deal_type": _at(d_deal_type, i, "paid"),
                "fee": _blank_none(_at(d_fee, i)),
                "barter_value": _blank_none(_at(d_barter_value, i)),
                "bonus_threshold": _blank_none(_at(d_bonus_threshold, i)),
                "bonus_amount": _blank_none(_at(d_bonus_amount, i)),
                "min_reach": _blank_none(_at(d_min_reach, i)) if reach_mode == "guarantee" else None,
                "min_reach_explicitly_none": reach_mode == "none",
                "due_day": _blank_none(_at(d_due_day, i)),
                "required_tag": required_tag, "required_hashtag": required_hashtag,
                "requires_link_sticker": requires_link_sticker,
                "waived_notes": waived_notes,
            })

        raw = {"source": source, "brief_text": brief_text, "creator": raw_creator, "deliverables": raw_deliverables}

    draft = intake.normalize_draft(conn, raw, campaign_row, st["current_day"], thresholds)
    errors = intake.validate_draft(draft, campaign_row, thresholds)
    blocking = [e for e in errors if e["blocking"]]
    if blocking:
        return _render_preview(request, conn, draft, blocking)

    result = intake.commit_intake(conn, draft, campaign_row, thresholds)
    return _render_preview(request, conn, draft, [], result)
