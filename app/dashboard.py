"""Aggregation layer between the rules engine and the screens. Each function
here returns a plain dict/list that a template (or a future JSON API for the
Claude Design frontend) can render directly."""

from __future__ import annotations

import sqlite3

from app.ai import provider as ai
from app.reliability import compute_reliability
from app.rules.engine import evaluate_campaign, evaluate_post

STATUS_ORDER = {"Act now": 0, "Needs a look": 1, "OK": 2}


def get_overview(conn: sqlite3.Connection, campaign_id: int, current_day: int) -> dict:
    duration_days = conn.execute(
        "SELECT duration_days FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()["duration_days"]
    results = evaluate_campaign(conn, campaign_id=campaign_id, current_day=current_day)

    # A deliverable intaken with a future due_day (app/intake.py) hasn't started
    # yet — it must not count in "posts due today" or drag the live-percentage
    # down before its own clock has started. by_status/opportunities/rows below
    # still include it (so it's visible on the board, just not due yet).
    due_results = [r for r in results if r["due_day"] <= current_day]

    total_due = len(due_results)
    posts_live = sum(
        1 for r in due_results
        if conn.execute(
            "SELECT posted_at FROM posts WHERE id = ?", (r["post_id"],)
        ).fetchone()["posted_at"] is not None
    )

    total_reach = 0
    total_promised = 0
    guaranteed_count = 0  # deliverables that actually carry a reach guarantee (excludes barter/affiliate)
    reach_unknown_count = 0  # due deliverables whose latest snapshot has no reach (public metrics tier)
    for r in due_results:
        # min_reach is resolved per-deal (app/rules/contract.py) — barter/affiliate
        # deliverables have none, and must not inflate the brand-facing promised figure.
        if r["min_reach"]:
            total_promised += r["min_reach"]
            guaranteed_count += 1
        latest = conn.execute(
            "SELECT reach FROM post_snapshots WHERE post_id = ? AND day_number <= ? "
            "ORDER BY day_number DESC LIMIT 1", (r["post_id"], current_day),
        ).fetchone()
        if latest is None or latest["reach"] is None:
            reach_unknown_count += 1
        else:
            total_reach += latest["reach"]

    by_status = {"Act now": 0, "Needs a look": 0, "OK": 0}
    opportunities = 0
    for r in results:
        by_status[r["status"]] += 1
        opportunities += len(r["opportunities"])

    rows = sorted(results, key=lambda r: (STATUS_ORDER[r["status"]], -r["max_severity"]))
    return {
        "campaign_id": campaign_id,
        "current_day": current_day,
        "duration_days": duration_days,
        "posts_live": posts_live,
        "total_due": total_due,
        "total_reach": total_reach,
        "total_promised": total_promised,
        "guaranteed_count": guaranteed_count,
        "reach_known_count": total_due - reach_unknown_count,
        "reach_unknown_count": reach_unknown_count,
        "posts_live_pct": round(100 * posts_live / total_due) if total_due else 0,
        "by_status": by_status,
        "opportunities": opportunities,
        "rows": rows,
    }


def _creator_deliverables(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> list[dict]:
    """Every one of a creator's deliverables in ONE campaign, evaluated — a real
    deal is often a package ("1 reel + 2 stories"), so this fetches ALL of them
    rather than picking an arbitrary one via .fetchone() the way the single-
    deliverable assumption used to. Filtered to campaign_id: a creator signed
    across multiple campaigns must not have another campaign's posts silently
    folded into this one's rollup or reliability score."""
    post_rows = conn.execute(
        "SELECT p.id FROM posts p JOIN deliverables d ON d.id = p.deliverable_id "
        "WHERE d.creator_id = ? AND d.campaign_id = ? ORDER BY d.promised_date, p.id",
        (creator_id, campaign_id),
    ).fetchall()
    results = [evaluate_post(conn, r["id"], current_day) for r in post_rows]

    # Human label ("Story 2 of 3"), derived by grouping on format in promised
    # order — never stored, so it can't drift the way posts.is_story did.
    counts_by_format: dict[str, int] = {}
    for r in results:
        counts_by_format[r["format"]] = counts_by_format.get(r["format"], 0) + 1
    seen: dict[str, int] = {}
    for r in results:
        seen[r["format"]] = seen.get(r["format"], 0) + 1
        total = counts_by_format[r["format"]]
        r["deliverable_label"] = (
            r["format"].capitalize() if total == 1
            else f"{r['format'].capitalize()} {seen[r['format']]} of {total}"
        )
    return results


def _rollup_campaign_status(deliverables: list[dict]) -> dict | None:
    """Worst status across a creator's whole package, plus a delivered counter —
    the honest replacement for reporting one arbitrary deliverable as 'the'
    campaign."""
    if not deliverables:
        return None
    worst = min(deliverables, key=lambda r: STATUS_ORDER[r["status"]])
    delivered = sum(1 for r in deliverables if not any(f["rule_id"] == 1 for f in r["flags"]))
    return {**worst, "delivered": delivered, "total_deliverables": len(deliverables)}


def get_flag_queue(conn: sqlite3.Connection, campaign_id: int, current_day: int, ai_enabled: bool) -> list[dict]:
    brand_name = conn.execute(
        "SELECT b.name FROM campaigns camp JOIN brands b ON b.id = camp.brand_id WHERE camp.id = ?",
        (campaign_id,),
    ).fetchone()["name"]
    results = evaluate_campaign(conn, campaign_id=campaign_id, current_day=current_day)
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
                    f["evidence"].get("creator_avg_reach_source"),
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
            suggested_message = ai.generate_nudge_message(ai_enabled, cinfo["handle"], top["rule_name"], top["reason"], brand_name)

        opportunity_note = None
        if r["opportunities"]:
            opp = r["opportunities"][0]
            opportunity_note = ai.suggest_boost(
                ai_enabled, cinfo["handle"], opp["evidence"]["multiplier"], cinfo["niche"], r["deal_type"],
            )

        # The rule a decision form submits against — a problem flag takes priority,
        # but an opportunity-only card (e.g. a viral winner) still needs one so its
        # suggested boost can go through the same Approve/Edit/Dismiss flow.
        primary_rule_id = enriched_flags[0]["rule_id"] if enriched_flags else (
            r["opportunities"][0]["rule_id"] if r["opportunities"] else None
        )

        cards.append({
            **r,
            "niche": cinfo["niche"],
            "flags": enriched_flags,
            "suggested_message": suggested_message,
            "opportunity_note": opportunity_note,
            "primary_rule_id": primary_rule_id,
            "default_message": suggested_message or opportunity_note,
        })
    return cards


def get_creator_package(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> dict:
    """The rolled-up status plus every deliverable for one creator IN ONE
    CAMPAIGN — the shared shape both get_creator_profile and the deal-intake
    confirmation screen (app/main.py's /intake/confirm) use to show the new
    rows flowing through the already-shipped rollup machinery immediately."""
    deliverables = _creator_deliverables(conn, campaign_id, creator_id, current_day)
    return {"current_campaign": _rollup_campaign_status(deliverables), "current_deliverables": deliverables}


def get_creator_list(conn: sqlite3.Connection, campaign_id: int, current_day: int) -> list[dict]:
    """The full creator roster — shared across every campaign, so switching
    campaigns never hides a creator — each enriched with their rollup for the
    ONE selected campaign. A creator not enrolled there shows current_campaign
    = None, same as "no deliverables yet" always has."""
    creators = []
    for r in conn.execute("SELECT id, handle, tier, niche, metrics_source FROM creators ORDER BY handle").fetchall():
        deliverables = _creator_deliverables(conn, campaign_id, r["id"], current_day)
        creators.append({
            **dict(r),
            "reliability": compute_reliability(conn, campaign_id, r["id"], current_day),
            "current_campaign": _rollup_campaign_status(deliverables),
        })
    creators.sort(key=lambda c: -(c["reliability"]["score"] if c["reliability"]["score"] is not None else -1))
    return creators


def _other_campaigns(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> list[dict]:
    """A creator's rolled-up status in every OTHER active campaign they're
    enrolled in — listed on the profile so excluding them from the selected
    campaign's own rollup (the scoping fix) doesn't read as hiding work."""
    other_ids = [
        row["id"] for row in conn.execute(
            "SELECT DISTINCT camp.id FROM campaigns camp "
            "JOIN deliverables d ON d.campaign_id = camp.id "
            "WHERE d.creator_id = ? AND camp.id != ? AND camp.status = 'active' ORDER BY camp.id",
            (creator_id, campaign_id),
        ).fetchall()
    ]
    out = []
    for other_id in other_ids:
        name = conn.execute("SELECT name FROM campaigns WHERE id = ?", (other_id,)).fetchone()["name"]
        deliverables = _creator_deliverables(conn, other_id, creator_id, current_day)
        rollup = _rollup_campaign_status(deliverables)
        out.append({"campaign_id": other_id, "campaign_name": name, "status": rollup["status"] if rollup else None})
    return out


def get_creator_profile(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> dict:
    creator = dict(conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone())
    reliability = compute_reliability(conn, campaign_id, creator_id, current_day)

    return {
        "creator": creator,
        "reliability": reliability,
        "other_campaigns": _other_campaigns(conn, campaign_id, creator_id, current_day),
        **get_creator_package(conn, campaign_id, creator_id, current_day),
    }


def get_brand_report(conn: sqlite3.Connection, campaign_id: int, current_day: int, ai_enabled: bool) -> dict:
    campaign_name = conn.execute("SELECT name FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()["name"]
    overview = get_overview(conn, campaign_id, current_day)
    results = evaluate_campaign(conn, campaign_id=campaign_id, current_day=current_day)

    highlights = []
    issues = []
    for r in results:
        if r["opportunities"]:
            highlights.append(f"@{r['handle']}: {r['opportunities'][0]['reason']}")
        if r["status"] == "Act now":
            issues.append(f"@{r['handle']}: {r['reason']}")

    text = ai.generate_brand_daily_report(
        ai_enabled, current_day, overview["duration_days"], overview["posts_live"], overview["total_due"],
        overview["total_reach"], overview["total_promised"], overview["by_status"]["Act now"],
        overview["by_status"]["Needs a look"], overview["by_status"]["OK"], highlights, issues, campaign_name,
    )
    return {"overview": overview, "highlights": highlights, "issues": issues, "text": text}
