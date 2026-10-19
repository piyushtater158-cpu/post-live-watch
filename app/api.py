"""JSON API for the standalone frontend (frontend/, deployed on Vercel). Every
endpoint returns the same dicts the Jinja2 templates render, so the two
surfaces can't disagree about what the engine computed."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import actions, dashboard, intake
from app.ai import provider as ai
from app.config import load_thresholds
from app.deps import get_db
from app.rules.engine import evaluate_campaign

router = APIRouter(prefix="/api", on_startup=[actions.warm_ai_cache])


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    message_text: str = ""
    original_message: str = ""
    flag_rule_id: int = 0


class BriefIn(BaseModel):
    brief_text: str = Field(min_length=1, max_length=4000)


class IntakeConfirmIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    # approve commits original_draft verbatim (like a flag decision's original_message);
    # edit commits `draft`, the AM's changed copy. Both are re-normalized and re-validated.
    original_draft: dict = Field(default_factory=dict)
    draft: dict | None = None


def _intake_response(conn: sqlite3.Connection, draft: dict, blocking: list[dict], result: dict | None = None) -> dict:
    st = actions.get_app_state(conn)
    draft = intake.attach_preview_notes(draft, intake.campaign_row(conn))
    package = dashboard.get_creator_package(conn, result["creator_id"], st["current_day"]) if result else None
    return {"draft": draft, "blocking_errors": blocking, "result": result, "package": package}


@router.get("/state")
def state(conn: sqlite3.Connection = Depends(get_db)):
    return actions.get_app_state(conn)


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return dashboard.get_overview(conn, st["current_day"])


@router.get("/queue")
def queue(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return {"cards": dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])}


@router.post("/flags/{post_id}/decide")
def decide(post_id: int, body: DecisionIn, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Post not found")
    st = actions.get_app_state(conn)
    actions.record_decision(
        conn, post_id, body.action, body.message_text, body.original_message, body.flag_rule_id, st["current_day"],
    )
    return {"cards": dashboard.get_flag_queue(conn, st["current_day"], st["ai_enabled"])}


@router.get("/creators")
def creators(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return {"creators": dashboard.get_creator_list(conn, st["current_day"])}


@router.get("/creators/{creator_id}")
def creator_profile(creator_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM creators WHERE id = ?", (creator_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    st = actions.get_app_state(conn)
    return dashboard.get_creator_profile(conn, creator_id, st["current_day"])


@router.get("/report")
def report(conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    return dashboard.get_brand_report(conn, st["current_day"], st["ai_enabled"])


@router.get("/decisions")
def decisions(conn: sqlite3.Connection = Depends(get_db)):
    return {"rows": actions.list_decisions(conn)}


@router.post("/simulate/advance-day")
def advance_day(conn: sqlite3.Connection = Depends(get_db)):
    return actions.advance_day(conn)


@router.post("/simulate/reset-day")
def reset_day(conn: sqlite3.Connection = Depends(get_db)):
    return actions.reset_day(conn)


@router.post("/settings/ai-toggle")
def toggle_ai(conn: sqlite3.Connection = Depends(get_db)):
    return actions.toggle_ai(conn)


@router.get("/intake")
def intake_defaults(conn: sqlite3.Connection = Depends(get_db)):
    c = intake.campaign_row(conn)
    return {"campaign": {k: c[k] for k in ("name", "required_tag", "required_hashtag", "required_disclosure",
                                           "requires_link_sticker", "duration_days")}}


@router.post("/intake/parse")
def intake_parse(body: BriefIn, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    campaign = intake.campaign_row(conn)
    thresholds = load_thresholds()
    raw = ai.parse_deal_brief(st["ai_enabled"], body.brief_text, campaign, st["current_day"],
                              campaign["duration_days"], intake.known_handles(conn))
    draft = intake.normalize_draft(conn, raw, campaign, st["current_day"], thresholds)
    errors = intake.validate_draft(draft, campaign, thresholds)
    return _intake_response(conn, draft, [e for e in errors if e["blocking"]])


@router.post("/intake/confirm")
def intake_confirm(body: IntakeConfirmIn, conn: sqlite3.Connection = Depends(get_db)):
    if body.action == "dismiss":
        return {"dismissed": True}
    st = actions.get_app_state(conn)
    campaign = intake.campaign_row(conn)
    thresholds = load_thresholds()
    raw = body.original_draft if body.action == "approve" else (body.draft or {})
    draft = intake.normalize_draft(conn, raw, campaign, st["current_day"], thresholds)
    blocking = [e for e in intake.validate_draft(draft, campaign, thresholds) if e["blocking"]]
    if blocking:
        return _intake_response(conn, draft, blocking)
    try:
        result = intake.commit_intake(conn, draft, campaign, thresholds)
    except intake.IntakeValidationError as exc:
        return _intake_response(conn, draft, exc.errors)
    return _intake_response(conn, draft, [], result)


@router.get("/debug")
def debug(conn: sqlite3.Connection = Depends(get_db)):
    """The engine's proof-of-correctness surface — full computed state per
    post, independent of any UI. This is what 'all 12 problems trigger on
    the right posts' is verified against in tests/test_rules.py, and what a
    reviewer can hit directly without clicking through screens."""
    st = actions.get_app_state(conn)
    results = evaluate_campaign(conn, campaign_id=1, current_day=st["current_day"])
    return {**st, "results": results}
