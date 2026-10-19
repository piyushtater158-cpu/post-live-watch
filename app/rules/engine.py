"""Runs all 12 detectors against a post and reduces them to a triage status.

Status is computed ONLY from negative-polarity flags' severities — a viral
winner (positive) never gets hidden behind an "OK" status; it's always
surfaced separately as an opportunity, per the brief's "Viral winner
(positive)" case.
"""

from __future__ import annotations

import sqlite3

from app.config import load_thresholds

from .context import load_post_context
from .detectors import ALL_DETECTORS


def _status_for_severity(max_severity: int, t: dict) -> str:
    cutoffs = t["severity_cutoffs"]
    if max_severity >= cutoffs["act_now"]:
        return "Act now"
    if max_severity >= cutoffs["needs_look"]:
        return "Needs a look"
    return "OK"


def evaluate_post(conn: sqlite3.Connection, post_id: int, current_day: int, thresholds: dict | None = None) -> dict:
    t = thresholds or load_thresholds()
    ctx = load_post_context(conn, post_id, current_day)

    all_flags = [d(ctx, t) for d in ALL_DETECTORS]
    all_flags = [f for f in all_flags if f is not None]

    negative = sorted([f for f in all_flags if f["polarity"] == "negative"], key=lambda f: -f["severity"])
    opportunities = [f for f in all_flags if f["polarity"] == "positive"]

    max_severity = negative[0]["severity"] if negative else 0
    status = _status_for_severity(max_severity, t)
    reason = negative[0]["reason"] if negative else (opportunities[0]["reason"] if opportunities else "No issues detected.")

    return {
        "post_id": post_id,
        "deliverable_id": ctx.deliverable_id,
        "creator_id": ctx.creator_id,
        "handle": ctx.creator_handle,
        "format": ctx.format,
        "due_day": ctx.due_day,
        "status": status,
        "max_severity": max_severity,
        "reason": reason,
        "flags": negative,
        "opportunities": opportunities,
        "deal_type": ctx.deal_type,
        "min_reach": ctx.min_reach,
        "contract_notes": ctx.contract_notes,
        "current_day": current_day,
    }


def evaluate_campaign(conn: sqlite3.Connection, campaign_id: int, current_day: int, thresholds: dict | None = None) -> list[dict]:
    t = thresholds or load_thresholds()
    post_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT p.id FROM posts p JOIN deliverables d ON d.id = p.deliverable_id "
            "WHERE d.campaign_id = ? ORDER BY p.id",
            (campaign_id,),
        ).fetchall()
    ]
    return [evaluate_post(conn, pid, current_day, t) for pid in post_ids]
