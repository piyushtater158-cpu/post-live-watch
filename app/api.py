"""JSON API for the standalone frontend (frontend/, deployed on Vercel). Every
endpoint returns the same dicts the Jinja2 templates render, so the two
surfaces can't disagree about what the engine computed.

Every GET below accepts an optional ?campaign_id= query param that overrides
the server's stored selection for that one read, without changing it — the
frontend uses this once it has a campaign switcher (Phase 2); until then it's
simply absent and every read falls back to the stored selection, identical to
today's single-campaign behavior."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import actions, campaign_intake, dashboard, intake
from app.ai import provider as ai
from app.config import load_thresholds
from app.deps import get_db
from app.rules.engine import evaluate_campaign

router = APIRouter(prefix="/api", on_startup=[actions.warm_ai_cache])


def _require_campaign(st: dict) -> int:
    if st["campaign_id"] is None:
        raise HTTPException(status_code=409, detail="No campaign exists yet — create one first.")
    return st["campaign_id"]


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    message_text: str = ""
    original_message: str = ""
    flag_rule_id: int = 0


class BriefIn(BaseModel):
    brief_text: str = Field(min_length=1, max_length=4000)


class CampaignFieldsIn(BaseModel):
    name: str = ""
    existing_brand_id: int | None = None
    brand_name: str = ""
    product: str = ""
    duration_days: int | None = None
    days_running: int | None = None
    required_disclosure: str = ""
    required_tag: str = ""
    required_hashtag: str = ""
    requires_link_sticker: bool = True
    banned_claims: list[str] = Field(default_factory=list)


class CampaignBriefIn(BaseModel):
    campaign: CampaignFieldsIn
    creators_brief_text: str = Field(default="", max_length=8000)


class CampaignConfirmIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    original_draft: dict = Field(default_factory=dict)
    draft: dict | None = None


class CampaignSelectIn(BaseModel):
    campaign_id: int


class CampaignClockIn(BaseModel):
    mode: Literal["live", "simulated"]


class CampaignEditIn(BaseModel):
    name: str
    required_disclosure: str
    required_tag: str = ""
    required_hashtag: str = ""
    requires_link_sticker: bool = True
    duration_days: int
    banned_claims: list[str] = Field(default_factory=list)
    metrics_provider: Literal["seeded", "manual", "instagram"] | None = None  # None = leave unchanged


class IntakeConfirmIn(BaseModel):
    action: Literal["approve", "edit", "dismiss"]
    # approve commits original_draft verbatim (like a flag decision's original_message);
    # edit commits `draft`, the AM's changed copy. Both are re-normalized and re-validated.
    original_draft: dict = Field(default_factory=dict)
    draft: dict | None = None


def _intake_response(conn: sqlite3.Connection, campaign_id: int, draft: dict, blocking: list[dict],
                      result: dict | None = None) -> dict:
    st = actions.get_app_state(conn, campaign_id)
    draft = intake.attach_preview_notes(draft, intake.campaign_row(conn, campaign_id))
    package = dashboard.get_creator_package(conn, campaign_id, result["creator_id"], st["current_day"]) if result else None
    return {"draft": draft, "blocking_errors": blocking, "result": result, "package": package}


@router.get("/state")
def state(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    return actions.get_app_state(conn, campaign_id)


@router.get("/overview")
def overview(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    return dashboard.get_overview(conn, _require_campaign(st), st["current_day"])


@router.get("/queue")
def queue(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    return {"cards": dashboard.get_flag_queue(conn, _require_campaign(st), st["current_day"], st["ai_enabled"])}


@router.post("/flags/{post_id}/decide")
def decide(post_id: int, body: DecisionIn, campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Post not found")
    st = actions.get_app_state(conn, campaign_id)
    actions.record_decision(
        conn, post_id, body.action, body.message_text, body.original_message, body.flag_rule_id, st["current_day"],
    )
    return {"cards": dashboard.get_flag_queue(conn, _require_campaign(st), st["current_day"], st["ai_enabled"])}


@router.get("/creators")
def creators(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    return {"creators": dashboard.get_creator_list(conn, _require_campaign(st), st["current_day"])}


@router.get("/creators/{creator_id}")
def creator_profile(creator_id: int, campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM creators WHERE id = ?", (creator_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    st = actions.get_app_state(conn, campaign_id)
    return dashboard.get_creator_profile(conn, _require_campaign(st), creator_id, st["current_day"])


@router.get("/report")
def report(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    return dashboard.get_brand_report(conn, _require_campaign(st), st["current_day"], st["ai_enabled"])


@router.get("/decisions")
def decisions(conn: sqlite3.Connection = Depends(get_db)):
    return {"rows": actions.list_decisions(conn)}


@router.post("/simulate/advance-day")
def advance_day(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    try:
        return actions.advance_day(conn, _require_campaign(st))
    except ValueError as exc:  # live-clock campaign
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/simulate/reset-day")
def reset_day(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    try:
        return actions.reset_day(conn, _require_campaign(st))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/ai-toggle")
def toggle_ai(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    return actions.toggle_ai(conn, campaign_id)


# ---------------------------------------------------------------------------
# Campaign management — JSON mirror of app/main.py's HTML routes. Returns the
# exact same dicts, same reasoning as the module docstring above.
# ---------------------------------------------------------------------------


@router.get("/campaigns")
def campaigns_list(conn: sqlite3.Connection = Depends(get_db)):
    return {"campaigns": actions.list_campaigns(conn)}


@router.get("/campaign-defaults")
def campaign_defaults(conn: sqlite3.Connection = Depends(get_db)):
    cfg = load_thresholds()["campaign_intake"]
    return {
        "brands": campaign_intake.list_brands(conn),
        "default_duration_days": cfg["default_duration_days"],
        "max_duration_days": cfg["max_duration_days"],
        "default_required_disclosure": cfg["default_required_disclosure"],
    }


@router.post("/campaigns/select")
def campaigns_select(body: CampaignSelectIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return actions.select_campaign(conn, body.campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/clock")
def campaigns_clock(campaign_id: int, body: CampaignClockIn, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return actions.set_clock_mode(conn, campaign_id, body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}")
def campaigns_get(campaign_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return intake.campaign_row(conn, campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/edit")
def campaigns_edit(campaign_id: int, body: CampaignEditIn, conn: sqlite3.Connection = Depends(get_db)):
    thresholds = load_thresholds()
    try:
        return campaign_intake.update_campaign_fields(conn, campaign_id, body.model_dump(), thresholds)
    except campaign_intake.CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc


@router.post("/campaigns/{campaign_id}/sync")
def campaigns_sync(campaign_id: int, conn: sqlite3.Connection = Depends(get_db)):
    from app.metrics.sync import run_sync
    try:
        return run_sync(conn, campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ManualMetricsIn(BaseModel):
    day_number: int
    reach: int | None = None
    likes: int = 0
    comments_count: int = 0
    saves: int | None = None
    shares: int | None = None
    still_live: bool = True


@router.post("/deliverables/{deliverable_id}/metrics")
def deliverable_metrics(deliverable_id: int, body: ManualMetricsIn, conn: sqlite3.Connection = Depends(get_db)):
    from app.metrics.manual import record_manual_snapshot
    post = conn.execute("SELECT id FROM posts WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
    if post is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    snapshot_id = record_manual_snapshot(
        conn, post["id"], body.day_number, body.reach, body.likes, body.comments_count,
        body.saves, body.shares, body.still_live,
    )
    return {"snapshot_id": snapshot_id, "post_id": post["id"]}


@router.get("/creators/research/{handle}")
def creators_research(handle: str):
    """Pre-signing research: pulls a creator's current followers and a
    MEASURED engagement rate from their recent public media — the honest
    upgrade path off app/intake.py's follower-count estimate, and the
    'doing our own research on Instagram' capability. Public tier only (see
    app/metrics/instagram.py:resolve_creator) — no deal exists yet, so there's
    no branded-content tag to read."""
    from app.metrics.base import NotConfigured
    from app.metrics.instagram import InstagramProvider
    try:
        provider = InstagramProvider()
    except NotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    info = provider.resolve_creator(handle)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Could not look up @{handle} — private, not found, or not a professional account.")
    return {"handle": handle, **info}


@router.get("/integrations/instagram")
def instagram_status(conn: sqlite3.Connection = Depends(get_db)):
    """Connection status for the Instagram screen. Reports WHICH credentials
    are missing, never their values."""
    from app.metrics import instagram
    from app.metrics.sync import recent_fetch_runs
    missing = instagram.missing_env()
    return {
        "configured": not missing,
        "missing_env": missing,
        "required_env": list(instagram.REQUIRED_ENV),
        "graph_version": instagram.graph_version(),
        "instagram_campaigns": [c for c in actions.list_campaigns(conn) if c["metrics_provider"] == "instagram"],
        "recent_runs": recent_fetch_runs(conn),
    }


@router.post("/integrations/instagram/test")
def instagram_test():
    from app.metrics.base import NotConfigured
    from app.metrics.instagram import InstagramProvider
    try:
        provider = InstagramProvider()
    except NotConfigured as exc:
        return {"ok": False, "error": str(exc), "account": None}
    try:
        return {"ok": True, "error": None, "account": provider.check_connection()}
    except Exception as exc:
        return {"ok": False, "error": _meta_error_message(exc), "account": None}


def _meta_error_message(exc: Exception) -> str:
    """Meta's own error text (e.g. 'Error validating access token') when the
    Graph API returned one, so the AM sees what to fix rather than a bare 400."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            return response.json()["error"]["message"]
        except Exception:
            return f"Meta returned HTTP {response.status_code}"
    return str(exc)


def _campaign_intake_response(draft: dict, blocking: list[dict], result: dict | None = None) -> dict:
    draft = campaign_intake.attach_preview_notes(draft)
    return {"draft": draft, "blocking_errors": blocking, "result": result}


@router.post("/campaigns/parse")
def campaigns_parse(body: CampaignBriefIn, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn)
    thresholds = load_thresholds()
    known_handles = intake.known_handles(conn)
    # Same division of labor as the HTML route: the typed campaign fields are
    # authoritative, only the creator deals get AI/keyword-drafted from text.
    parsed = ai.parse_campaign_brief(st["ai_enabled"], body.creators_brief_text, known_handles)
    raw = {
        "source": parsed.get("source", "form"), "brief_text": body.creators_brief_text,
        "campaign": body.campaign.model_dump(), "creators": parsed["creators"],
    }
    draft = campaign_intake.normalize_campaign_draft(conn, raw, datetime.now(), thresholds)
    errors = campaign_intake.validate_campaign_draft(draft, thresholds)
    return _campaign_intake_response(draft, [e for e in errors if e["blocking"]])


@router.post("/campaigns/confirm")
def campaigns_confirm(body: CampaignConfirmIn, conn: sqlite3.Connection = Depends(get_db)):
    if body.action == "dismiss":
        return {"dismissed": True}
    thresholds = load_thresholds()
    raw = body.original_draft if body.action == "approve" else (body.draft or {})
    draft = campaign_intake.normalize_campaign_draft(conn, raw, datetime.now(), thresholds)
    blocking = [e for e in campaign_intake.validate_campaign_draft(draft, thresholds) if e["blocking"]]
    if blocking:
        return _campaign_intake_response(draft, blocking)
    try:
        result = campaign_intake.commit_campaign(conn, draft, thresholds)
    except campaign_intake.CampaignValidationError as exc:
        return _campaign_intake_response(draft, exc.errors)
    return _campaign_intake_response(draft, [], result)


@router.get("/intake")
def intake_defaults(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    c = intake.campaign_row(conn, _require_campaign(st))
    return {"campaign": {k: c[k] for k in ("name", "required_tag", "required_hashtag", "required_disclosure",
                                           "requires_link_sticker", "duration_days")}}


@router.post("/intake/parse")
def intake_parse(body: BriefIn, campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    st = actions.get_app_state(conn, campaign_id)
    cid = _require_campaign(st)
    campaign = intake.campaign_row(conn, cid)
    thresholds = load_thresholds()
    raw = ai.parse_deal_brief(st["ai_enabled"], body.brief_text, campaign, st["current_day"],
                              campaign["duration_days"], intake.known_handles(conn))
    draft = intake.normalize_draft(conn, raw, campaign, st["current_day"], thresholds)
    errors = intake.validate_draft(draft, campaign, thresholds)
    return _intake_response(conn, cid, draft, [e for e in errors if e["blocking"]])


@router.post("/intake/confirm")
def intake_confirm(body: IntakeConfirmIn, campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    if body.action == "dismiss":
        return {"dismissed": True}
    st = actions.get_app_state(conn, campaign_id)
    cid = _require_campaign(st)
    campaign = intake.campaign_row(conn, cid)
    thresholds = load_thresholds()
    raw = body.original_draft if body.action == "approve" else (body.draft or {})
    draft = intake.normalize_draft(conn, raw, campaign, st["current_day"], thresholds)
    blocking = [e for e in intake.validate_draft(draft, campaign, thresholds) if e["blocking"]]
    if blocking:
        return _intake_response(conn, cid, draft, blocking)
    try:
        result = intake.commit_intake(conn, draft, campaign, thresholds)
    except intake.IntakeValidationError as exc:
        return _intake_response(conn, cid, draft, exc.errors)
    return _intake_response(conn, cid, draft, [], result)


@router.get("/debug")
def debug(campaign_id: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    """The engine's proof-of-correctness surface — full computed state per
    post, independent of any UI. This is what 'all 12 problems trigger on
    the right posts' is verified against in tests/test_rules.py, and what a
    reviewer can hit directly without clicking through screens."""
    st = actions.get_app_state(conn, campaign_id)
    results = evaluate_campaign(conn, campaign_id=_require_campaign(st), current_day=st["current_day"])
    return {**st, "results": results}
