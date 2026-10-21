from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import actions, campaign_intake, dashboard, intake
from app.ai import provider as ai
from app.api import router as api_router
from app.config import load_thresholds
from app.db import get_campaign_day, get_connection, init_schema
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
    data = dashboard.get_overview(conn, st["campaign_id"], st["current_day"])
    return templates.TemplateResponse("index.html", {"request": request, "active_nav": "overview", **st, **data})


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    cards = dashboard.get_flag_queue(conn, st["campaign_id"], st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("queue.html", {"request": request, "active_nav": "queue", **st, "cards": cards})


@app.get("/creators", response_class=HTMLResponse)
def creators_list(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    creators = dashboard.get_creator_list(conn, st["campaign_id"], st["current_day"])
    return templates.TemplateResponse("creators.html", {"request": request, "active_nav": "creators", **st, "creators": creators})


@app.get("/creators/{creator_id}", response_class=HTMLResponse)
def creator_profile(request: Request, creator_id: int, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    profile = dashboard.get_creator_profile(conn, st["campaign_id"], creator_id, st["current_day"])
    return templates.TemplateResponse("creator_profile.html", {"request": request, "active_nav": "creators", **st, **profile})


@app.get("/report", response_class=HTMLResponse)
def brand_report(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    report = dashboard.get_brand_report(conn, st["campaign_id"], st["current_day"], st["ai_enabled"])
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
    cards = dashboard.get_flag_queue(conn, st["campaign_id"], st["current_day"], st["ai_enabled"])
    return templates.TemplateResponse("_queue_list.html", {"request": request, **st, "cards": cards})


@app.get("/decisions", response_class=HTMLResponse)
def decision_log(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    rows = actions.list_decisions(conn)
    return templates.TemplateResponse("decisions.html", {"request": request, "active_nav": "decisions", **st, "rows": rows})


@app.post("/simulate/advance-day")
def advance_day(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    try:
        actions.advance_day(conn, st["campaign_id"])
    except ValueError as exc:  # live-clock campaign, or no campaign selected
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url="/", status_code=303)


@app.post("/simulate/reset-day")
def reset_day(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    try:
        actions.reset_day(conn, st["campaign_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url="/", status_code=303)


@app.post("/settings/ai-toggle")
def toggle_ai(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    actions.toggle_ai(conn, st["campaign_id"])
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Campaign management — create a brand-new or already-in-flight campaign,
# switch which one the rest of the app is showing, add creators to it (the
# existing /intake flow below, now campaign-scoped), and edit its brief
# fields after the fact. See app/campaign_intake.py's module docstring.
# ---------------------------------------------------------------------------


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_list(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return templates.TemplateResponse("campaigns.html", {"request": request, "active_nav": "campaigns", **st})


@app.post("/campaigns/select")
def select_campaign(campaign_id: int = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    actions.select_campaign(conn, campaign_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/campaigns/{campaign_id}/clock")
def set_campaign_clock(campaign_id: int, mode: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    try:
        actions.set_clock_mode(conn, campaign_id, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/campaigns", status_code=303)


@app.post("/campaigns/{campaign_id}/sync", response_class=HTMLResponse)
def campaign_sync(request: Request, campaign_id: int, conn: sqlite3.Connection = Depends(get_db)):
    from app.metrics.sync import run_sync
    try:
        result = run_sync(conn, campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    st = actions.get_app_state(conn)
    return templates.TemplateResponse("_sync_result.html", {"request": request, **st, "result": result})


@app.get("/deliverables/{deliverable_id}/metrics", response_class=HTMLResponse)
def deliverable_metrics_form(request: Request, deliverable_id: int, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    row = conn.execute(
        "SELECT d.id AS deliverable_id, d.format, d.campaign_id, c.handle, p.id AS post_id "
        "FROM deliverables d JOIN creators c ON c.id = d.creator_id JOIN posts p ON p.deliverable_id = d.id "
        "WHERE d.id = ?", (deliverable_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    # The deliverable's OWN campaign's day, not whichever campaign happens to be
    # globally selected — a creator's deliverable in campaign A must prefill
    # campaign A's current day even while campaign B is the active one in the nav.
    deliverable_day = get_campaign_day(conn, row["campaign_id"])
    return templates.TemplateResponse("_metrics_form.html", {
        "request": request, **{**st, "current_day": deliverable_day}, "deliverable": dict(row),
    })


@app.post("/deliverables/{deliverable_id}/metrics", response_class=HTMLResponse)
def deliverable_metrics_submit(
    request: Request, deliverable_id: int,
    day_number: int = Form(...), reach: str = Form(""), likes: str = Form("0"),
    comments_count: str = Form("0"), saves: str = Form(""), shares: str = Form(""),
    still_live: str = Form(""), conn: sqlite3.Connection = Depends(get_db),
):
    from app.metrics.manual import record_manual_snapshot
    post = conn.execute("SELECT id FROM posts WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
    if post is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    record_manual_snapshot(
        conn, post["id"], day_number,
        int(reach) if reach.strip() else None, int(likes or 0), int(comments_count or 0),
        int(saves) if saves.strip() else None, int(shares) if shares.strip() else None,
        still_live == "on",
    )
    return RedirectResponse(url=f"/creators/{conn.execute('SELECT creator_id FROM deliverables WHERE id = ?', (deliverable_id,)).fetchone()['creator_id']}", status_code=303)


@app.get("/campaigns/new", response_class=HTMLResponse)
def campaign_new_form(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return templates.TemplateResponse("campaign_new.html", {
        "request": request, "active_nav": "campaigns", **st,
        "brands": campaign_intake.list_brands(conn),
        "default_duration_days": load_thresholds()["campaign_intake"]["default_duration_days"],
        "default_required_disclosure": load_thresholds()["campaign_intake"]["default_required_disclosure"],
    })


def _render_campaign_preview(request: Request, conn: sqlite3.Connection, draft: dict,
                              blocking_errors: list[dict], result: dict | None = None) -> HTMLResponse:
    st = actions.get_app_state(conn)
    draft = campaign_intake.attach_preview_notes(draft)
    return templates.TemplateResponse("_campaign_preview.html", {
        "request": request, **st, "draft": draft, "blocking_errors": blocking_errors, "result": result,
    })


def _campaign_raw_from_form(
    name: str, existing_brand_id: str, brand_name: str, product: str,
    duration_days: str, days_running: str, required_disclosure: str, required_tag: str,
    required_hashtag: str, requires_link_sticker: str, banned_claims_text: str,
    creators_brief_text: str, source: str,
) -> dict:
    banned_claims = [line.strip() for line in banned_claims_text.splitlines() if line.strip()]
    return {
        "source": source, "brief_text": creators_brief_text,
        "campaign": {
            "name": name, "existing_brand_id": int(existing_brand_id) if existing_brand_id else None,
            "brand_name": brand_name, "product": product,
            "duration_days": int(duration_days) if duration_days else None,
            "days_running": int(days_running) if days_running else None,
            "required_disclosure": required_disclosure, "required_tag": required_tag,
            "required_hashtag": required_hashtag, "requires_link_sticker": requires_link_sticker == "on",
            "banned_claims": banned_claims,
        },
        "creators": [],  # filled in by the caller once the creators_brief_text is parsed
    }


@app.post("/campaigns/parse", response_class=HTMLResponse)
def campaign_parse(
    request: Request,
    name: str = Form(...), existing_brand_id: str = Form(""), brand_name: str = Form(""),
    product: str = Form(""), duration_days: str = Form(""), days_running: str = Form(""),
    required_disclosure: str = Form(""), required_tag: str = Form(""), required_hashtag: str = Form(""),
    requires_link_sticker: str = Form(""), banned_claims_text: str = Form(""),
    creators_brief_text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    st = actions.get_app_state(conn)
    thresholds = load_thresholds()
    known_handles = intake.known_handles(conn)
    # The typed campaign fields are authoritative — only the creator deals get
    # AI/keyword-drafted from free text, same division of labor app/intake.py
    # already has between a human-entered form and an AI-assisted draft.
    parsed = ai.parse_campaign_brief(st["ai_enabled"], creators_brief_text, known_handles)
    raw = _campaign_raw_from_form(name, existing_brand_id, brand_name, product, duration_days, days_running,
                                   required_disclosure, required_tag, required_hashtag, requires_link_sticker,
                                   banned_claims_text, creators_brief_text, parsed.get("source", "form"))
    raw["creators"] = parsed["creators"]
    draft = campaign_intake.normalize_campaign_draft(conn, raw, datetime.now(), thresholds)
    errors = campaign_intake.validate_campaign_draft(draft, thresholds)
    return _render_campaign_preview(request, conn, draft, [e for e in errors if e["blocking"]])


@app.post("/campaigns/confirm", response_class=HTMLResponse)
def campaign_confirm(
    request: Request, action: str = Form(...), original_draft: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db),
):
    thresholds = load_thresholds()
    if action == "dismiss":
        return _render_campaign_preview(request, conn, {
            "source": "form", "brief_text": "", "campaign": {"name": "", "banned_claims": []},
            "creators": [], "warnings": [], "errors": [],
        }, [])

    raw = json.loads(original_draft) if original_draft else {}
    draft = campaign_intake.normalize_campaign_draft(conn, raw, datetime.now(), thresholds)
    errors = campaign_intake.validate_campaign_draft(draft, thresholds)
    blocking = [e for e in errors if e["blocking"]]
    if blocking:
        return _render_campaign_preview(request, conn, draft, blocking)

    try:
        result = campaign_intake.commit_campaign(conn, draft, thresholds)
    except campaign_intake.CampaignValidationError as exc:
        return _render_campaign_preview(request, conn, draft, exc.errors)
    return _render_campaign_preview(request, conn, draft, [], result)


@app.get("/campaigns/{campaign_id}/edit", response_class=HTMLResponse)
def campaign_edit_form(request: Request, campaign_id: int, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    try:
        campaign = intake.campaign_row(conn, campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    campaign["banned_claims_text"] = "\n".join(json.loads(campaign["banned_claims"] or "[]"))
    return templates.TemplateResponse("campaign_edit.html", {
        "request": request, "active_nav": "campaigns", **st, "campaign": campaign, "errors": [],
        "max_duration_days": load_thresholds()["campaign_intake"]["max_duration_days"],
    })


@app.post("/campaigns/{campaign_id}/edit", response_class=HTMLResponse)
def campaign_edit_submit(
    request: Request, campaign_id: int,
    name: str = Form(...), required_disclosure: str = Form(...), required_tag: str = Form(""),
    required_hashtag: str = Form(""), requires_link_sticker: str = Form(""),
    duration_days: str = Form(...), banned_claims_text: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db),
):
    thresholds = load_thresholds()
    fields = {
        "name": name, "required_disclosure": required_disclosure, "required_tag": required_tag,
        "required_hashtag": required_hashtag, "requires_link_sticker": requires_link_sticker == "on",
        "duration_days": int(duration_days) if duration_days.strip() else None,
        "banned_claims": [line.strip() for line in banned_claims_text.splitlines() if line.strip()],
    }
    try:
        campaign_intake.update_campaign_fields(conn, campaign_id, fields, thresholds)
    except campaign_intake.CampaignValidationError as exc:
        st = actions.get_app_state(conn)
        return templates.TemplateResponse("campaign_edit.html", {
            "request": request, "active_nav": "campaigns", **st,
            "campaign": {**fields, "id": campaign_id, "banned_claims_text": banned_claims_text}, "errors": exc.errors,
            "max_duration_days": thresholds["campaign_intake"]["max_duration_days"],
        })
    return RedirectResponse(url="/campaigns", status_code=303)


# ---------------------------------------------------------------------------
# Deal intake — turns an AM's free-text brief into real creators/deliverables/
# posts rows, with AI (or its deterministic fallback) only ever drafting and a
# human always confirming. See app/intake.py's module docstring for why that
# approval step is mandatory rather than a nice-to-have.
# ---------------------------------------------------------------------------


def _render_preview(request: Request, conn: sqlite3.Connection, draft: dict, blocking_errors: list[dict],
                     result: dict | None = None) -> HTMLResponse:
    st = actions.get_app_state(conn)
    campaign_row = intake.campaign_row(conn, st["campaign_id"])
    draft = intake.attach_preview_notes(draft, campaign_row)
    package = dashboard.get_creator_package(conn, st["campaign_id"], result["creator_id"], st["current_day"]) if result else None
    return templates.TemplateResponse("_intake_preview.html", {
        "request": request, **st, "draft": draft, "blocking_errors": blocking_errors,
        "result": result, "package": package, "campaign": campaign_row,
    })


@app.get("/intake", response_class=HTMLResponse)
def intake_form(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return templates.TemplateResponse("intake.html", {
        "request": request, "active_nav": "intake", **st, "campaign": intake.campaign_row(conn, st["campaign_id"]),
    })


@app.post("/intake/parse", response_class=HTMLResponse)
def intake_parse(request: Request, brief_text: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    campaign_row = intake.campaign_row(conn, st["campaign_id"])
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
    campaign_row = intake.campaign_row(conn, st["campaign_id"])
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
