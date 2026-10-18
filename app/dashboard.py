"""Aggregation layer between the rules engine and the screens. Each function
here returns a plain dict/list that a template (or a future JSON API for the
Claude Design frontend) can render directly."""

from __future__ import annotations

import sqlite3

from app.ai import provider as ai
from app.reliability import compute_reliability
from app.rules.engine import evaluate_campaign, evaluate_post

STATUS_ORDER = {"Act now": 0, "Needs a look": 1, "OK": 2}


def get_overview(conn: sqlite3.Connection, current_day: int) -> dict:
    results = evaluate_campaign(conn, campaign_id=1, current_day=current_day)

    total_due = len(results)
    posts_live = sum(
        1 for r in results
        if conn.execute(
            "SELECT posted_at FROM posts WHERE id = ?", (r["post_id"],)
        ).fetchone()["posted_at"] is not None
    )

    total_reach = 0
    total_promised = 0
    for r in results:
        row = conn.execute(
            "SELECT d.min_reach, p.id as pid FROM posts p JOIN deliverables d ON d.id = p.deliverable_id "
            "WHERE p.id = ?", (r["post_id"],),
        ).fetchone()
        total_promised += row["min_reach"]
        latest = conn.execute(
            "SELECT reach FROM post_snapshots WHERE post_id = ? AND day_number <= ? "
            "ORDER BY day_number DESC LIMIT 1", (r["post_id"], current_day),
        ).fetchone()
        total_reach += latest["reach"] if latest else 0

    by_status = {"Act now": 0, "Needs a look": 0, "OK": 0}
    opportunities = 0
    for r in results:
        by_status[r["status"]] += 1
        opportunities += len(r["opportunities"])

    rows = sorted(results, key=lambda r: (STATUS_ORDER[r["status"]], -r["max_severity"]))
    return {
        "current_day": current_day,
        "duration_days": 7,
        "posts_live": posts_live,
        "total_due": total_due,
        "total_reach": total_reach,
        "total_promised": total_promised,
        "by_status": by_status,
        "opportunities": opportunities,
        "rows": rows,
    }


def get_flag_queue(conn: sqlite3.Connection, current_day: int, ai_enabled: bool) -> list[dict]:
    results = evaluate_campaign(conn, campaign_id=1, current_day=current_day)
    flagged = [r for r in results if r["status"] != "OK" or r["opportunities"]]
    flagged.sort(key=lambda r: (STATUS_ORDER[r["status"]], -r["max_severity"]))

    cards = []
    for r in flagged:
        cinfo = conn.execute(
            "SELECT c.handle, c.niche, c.avg_reach, d.min_reach, p.caption, p.original_caption "
            "FROM posts p JOIN deliverables d ON d.id = p.deliverable_id "
            "JOIN creators c ON c.id = d.creator_id WHERE p.id = ?",
            (r["post_id"],),
        ).fetchone()

        enriched_flags = []
        for f in r["flags"]:
            extra = None
            if f["rule_id"] == 5:
                extra = ai.explain_underperformance(
                    ai_enabled, cinfo["handle"], f["evidence"]["reach"], f["evidence"]["min_reach"],
                    f["evidence"]["creator_avg_reach"], cinfo["niche"], r["format"],
                )
            elif f["rule_id"] == 7:
                sentiment = ai.classify_sentiment(ai_enabled, [
                    {"text": t} for t in f["evidence"].get("matched_comments", [])
                ])
                extra = sentiment["summary"]
            elif f["rule_id"] == 9:
                extra = ai.detect_paraphrased_claim(
                    ai_enabled, cinfo["original_caption"], cinfo["caption"], f["evidence"].get("banned_hits", [])
                )
            enriched_flags.append({**f, "ai_note": extra})

        suggested_message = None
        if enriched_flags:
            top = enriched_flags[0]
            suggested_message = ai.generate_nudge_message(ai_enabled, cinfo["handle"], top["rule_name"], top["reason"])

        opportunity_note = None
        if r["opportunities"]:
            opp = r["opportunities"][0]
            opportunity_note = ai.suggest_boost(ai_enabled, cinfo["handle"], opp["evidence"]["multiplier"], cinfo["niche"])

        cards.append({
            **r,
            "handle": cinfo["handle"],
            "niche": cinfo["niche"],
            "flags": enriched_flags,
            "suggested_message": suggested_message,
            "opportunity_note": opportunity_note,
        })
    return cards


def get_creator_list(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT id, handle, tier, niche FROM creators ORDER BY handle").fetchall()]


def get_creator_profile(conn: sqlite3.Connection, creator_id: int, current_day: int) -> dict:
    creator = dict(conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone())
    reliability = compute_reliability(conn, creator_id, current_day)

    post_row = conn.execute(
        "SELECT p.id FROM posts p JOIN deliverables d ON d.id = p.deliverable_id WHERE d.creator_id = ?",
        (creator_id,),
    ).fetchone()
    current_result = evaluate_post(conn, post_row["id"], current_day) if post_row else None

    return {
        "creator": creator,
        "reliability": reliability,
        "current_campaign": current_result,
    }


def get_brand_report(conn: sqlite3.Connection, current_day: int, ai_enabled: bool) -> dict:
    overview = get_overview(conn, current_day)
    results = evaluate_campaign(conn, campaign_id=1, current_day=current_day)

    highlights = []
    issues = []
    for r in results:
        if r["opportunities"]:
            highlights.append(f"@{r['creator_handle']}: {r['opportunities'][0]['reason']}")
        if r["status"] == "Act now":
            issues.append(f"@{r['creator_handle']}: {r['reason']}")

    text = ai.generate_brand_daily_report(
        ai_enabled, current_day, overview["duration_days"], overview["posts_live"], overview["total_due"],
        overview["total_reach"], overview["total_promised"], overview["by_status"]["Act now"],
        overview["by_status"]["Needs a look"], overview["by_status"]["OK"], highlights, issues,
    )
    return {"overview": overview, "highlights": highlights, "issues": issues, "text": text}
