"""Transparent, weighted reliability score for a creator's profile.

Score (0-100) = 100 * (
    0.40 * on_time_rate +
    0.25 * min(avg_performance_ratio, 1.2) / 1.2 +
    0.20 * (1 - min(avg_flags_per_campaign / 3, 1)) +
    0.15 * (1 - competitor_conflict_rate)
)

Every weight and cap lives here, in one place, matching the brief's demand
for a "transparent weighted formula" — not a black box.

A campaign with no reach guarantee (barter/affiliate) has no performance ratio,
so it's left out of the performance average rather than counted as 0x. A
creator with no history and nothing due yet (a brand-new deal-intake signing)
has no evidence at all, and gets no score — never a confident "book again".
"""

from __future__ import annotations

import sqlite3

from app.rules.engine import evaluate_post

WEIGHTS = {"on_time": 0.40, "performance": 0.25, "flags": 0.20, "competitor": 0.15}
PERFORMANCE_CAP = 1.2
FLAGS_PER_CAMPAIGN_CAP = 3


def _current_campaign_point(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> dict | None:
    """Aggregates across EVERY deliverable a creator has in ONE campaign — a real
    deal is often a package ("1 reel + 2 stories"), not a single post, so this can
    no longer pick an arbitrary one via .fetchone(). Filtered to campaign_id: a
    creator signed across multiple campaigns must not have one campaign's flags
    and performance silently blended into another's reliability score."""
    post_rows = conn.execute(
        "SELECT p.id, p.posted_at, d.min_reach FROM posts p "
        "JOIN deliverables d ON d.id = p.deliverable_id "
        "WHERE d.creator_id = ? AND d.campaign_id = ? ORDER BY p.id",
        (creator_id, campaign_id),
    ).fetchall()
    if not post_rows:
        return None

    performance_ratios = []
    flags_count = 0
    delivered_on_time = True
    competitor_conflict = False
    due_count = 0

    for post_row in post_rows:
        result = evaluate_post(conn, post_row["id"], current_day)
        if result["due_day"] > current_day:
            # Not due yet (e.g. a deal-intake brief signed for a few days from
            # now, app/intake.py) — nothing meaningful to measure about a deal
            # that hasn't started. Must not drag the score down before its own
            # clock has even begun.
            continue
        due_count += 1
        if any(f["rule_id"] in (1, 2) for f in result["flags"]):
            delivered_on_time = False
        flags_count += len(result["flags"])
        if any(f["rule_id"] == 11 for f in result["flags"]):
            competitor_conflict = True

        # Only deliverables that carry a reach guarantee contribute to performance —
        # a barter/no-guarantee deal has nothing to compute a ratio against.
        if post_row["min_reach"]:
            latest = conn.execute(
                "SELECT reach FROM post_snapshots WHERE post_id = ? AND day_number <= ? "
                "ORDER BY day_number DESC LIMIT 1",
                (post_row["id"], current_day),
            ).fetchone()
            # A missing snapshot and a snapshot with no reach (the public metrics
            # tier never returns it) are both "unknown", not "zero" — scoring an
            # unmeasured post as a 0x performer would be a false negative exactly
            # like treating a barter deal's absent min_reach as a 0x would be.
            if latest is not None and latest["reach"] is not None:
                performance_ratios.append(latest["reach"] / post_row["min_reach"])

    if due_count == 0:
        return None
    performance_ratio = sum(performance_ratios) / len(performance_ratios) if performance_ratios else None

    return {
        "delivered_on_time": delivered_on_time,
        "performance_ratio": performance_ratio,
        "flags_count": flags_count,
        "competitor_conflict": competitor_conflict,
    }


def compute_reliability(conn: sqlite3.Connection, campaign_id: int, creator_id: int, current_day: int) -> dict:
    historical = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM historical_campaigns WHERE creator_id = ? ORDER BY month ASC",
            (creator_id,),
        ).fetchall()
    ]

    points = [
        {
            "delivered_on_time": bool(h["delivered_on_time"]),
            "performance_ratio": h["performance_ratio"],
            "flags_count": h["flags_count"],
            "competitor_conflict": bool(h["competitor_conflict"]),
        }
        for h in historical
    ]

    current = _current_campaign_point(conn, campaign_id, creator_id, current_day)
    if current is not None:
        points.append(current)

    if not points:
        return {
            "creator_id": creator_id, "score": None, "on_time_rate": None, "avg_performance_ratio": None,
            "avg_flags_per_campaign": None, "competitor_conflict_rate": None, "campaigns_considered": 0,
            "book_again_hint": "New — no track record yet", "history": historical,
        }

    n = len(points)
    on_time_rate = sum(1 for p in points if p["delivered_on_time"]) / n
    ratios = [p["performance_ratio"] for p in points if p["performance_ratio"] is not None]
    avg_performance_ratio = sum(ratios) / len(ratios) if ratios else None
    avg_flags_per_campaign = sum(p["flags_count"] for p in points) / n
    competitor_conflict_rate = sum(1 for p in points if p["competitor_conflict"]) / n

    components = {
        "on_time": on_time_rate,
        "flags": 1 - min(avg_flags_per_campaign / FLAGS_PER_CAMPAIGN_CAP, 1),
        "competitor": 1 - competitor_conflict_rate,
    }
    if avg_performance_ratio is not None:
        components["performance"] = min(avg_performance_ratio, PERFORMANCE_CAP) / PERFORMANCE_CAP
    # Without any guaranteed-reach campaign, the remaining weights are rescaled to sum to 1.
    weight_total = sum(WEIGHTS[k] for k in components)
    score = 100 * sum(WEIGHTS[k] * v for k, v in components.items()) / weight_total
    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 75:
        book_again = "Yes — book again"
    elif score >= 50:
        book_again = "Maybe — review flags first"
    else:
        book_again = "Caution — review before rebooking"

    return {
        "creator_id": creator_id,
        "score": score,
        "on_time_rate": round(on_time_rate, 2),
        "avg_performance_ratio": round(avg_performance_ratio, 2) if avg_performance_ratio is not None else None,
        "avg_flags_per_campaign": round(avg_flags_per_campaign, 2),
        "competitor_conflict_rate": round(competitor_conflict_rate, 2),
        "campaigns_considered": n,
        "book_again_hint": book_again,
        "history": historical,
    }
