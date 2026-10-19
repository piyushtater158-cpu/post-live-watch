#!/usr/bin/env python
"""Generates the synthetic GlowLeaf campaign dataset for Post-Live Watch.

ALL DATA GENERATED HERE IS SAMPLE DATA — fictional brand, fictional creators,
fictional metrics. Nothing in this file touches a real Instagram account.

Run:
    python scripts/seed.py            # creates data/postlivewatch.db
    python scripts/seed.py --reset    # wipes and recreates it
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB_PATH, get_connection, init_schema, set_state  # noqa: E402

RNG = random.Random(42)

CAMPAIGN_START = datetime(2026, 9, 1, 9, 0, 0)
DURATION_DAYS = 7

BANNED_CLAIMS = ["cures acne", "100% natural", "dermatologist approved"]
REQUIRED_DISCLOSURE = "#ad|paid partnership"  # '|'-separated accepted tokens; resolved in app/rules/contract.py
REQUIRED_TAG = "@glowleaf"
REQUIRED_HASHTAG = "#GlowWithGlowLeaf"

# Per-deliverable negotiated overrides on the campaign brief above. Absent
# keys inherit the campaign default (resolved in app/rules/contract.py).
# '' on required_tag/required_hashtag means that requirement was waived
# entirely for this deal — different from "inherit", which is simply absent
# from this dict.
DELIVERABLE_OVERRIDES: dict[int, dict] = {
    5: {  # Barter deal: product given, no cash fee, no reach guarantee negotiated.
        "deal_type": "barter", "fee": None, "min_reach": None, "barter_value": 4000,
    },
    14: {  # Hashtag waived for this deal — demonstrates a negotiated term
          # coexisting with real flags (this post already fires rules 3 and 9).
        "required_hashtag": "",
        "waived_notes": {"required_hashtag": "Negotiated out — exclusivity clause with a rival campaign this month."},
    },
    20: {  # Affiliate deal: no cash fee, no reach guarantee, paid via commission instead.
        "deal_type": "affiliate", "fee": None, "min_reach": None,
    },
}

COMPLIANT_CAPTION = (
    "New skincare era unlocked ✨ Obsessed with how my skin feels after using "
    "this Vitamin C serum! #ad @glowleaf #GlowWithGlowLeaf #skincare"
)


def at(day_number: int, hour: int = 9, minute: int = 0) -> datetime:
    base = CAMPAIGN_START + timedelta(days=day_number - 1)
    return base.replace(hour=hour, minute=minute)


def curve(final_reach: float, days: int = DURATION_DAYS, start_frac: float = 0.35) -> list[int]:
    """Diminishing-returns growth curve that lands exactly on final_reach at day `days`."""
    return [round(final_reach * (start_frac + (1 - start_frac) * d / days)) for d in range(1, days + 1)]


def metrics_from_reach(reach: int, engagement_rate: float) -> tuple[int, int, int, int]:
    likes = round(reach * engagement_rate * 0.75)
    comments = round(reach * engagement_rate * 0.10)
    saves = round(reach * engagement_rate * 0.10)
    shares = round(reach * engagement_rate * 0.05)
    return likes, max(comments, 1), saves, shares


# ---------------------------------------------------------------------------
# Creators: 4 mid-tier (100k-500k followers), 16 micro (10k-100k)
# ---------------------------------------------------------------------------

CREATORS = [
    {"id": 1, "handle": "glow_with_meera", "followers": 180000, "tier": "mid", "niche": "skincare", "avg_reach": 54000, "avg_engagement_rate": 0.055},
    {"id": 2, "handle": "skinsutra_official", "followers": 250000, "tier": "mid", "niche": "skincare", "avg_reach": 70000, "avg_engagement_rate": 0.040},
    {"id": 3, "handle": "beautybynisha", "followers": 310000, "tier": "mid", "niche": "beauty", "avg_reach": 85000, "avg_engagement_rate": 0.050},
    {"id": 4, "handle": "thedailyglowup", "followers": 460000, "tier": "mid", "niche": "lifestyle", "avg_reach": 110000, "avg_engagement_rate": 0.035},
    {"id": 5, "handle": "chaiandcollagen", "followers": 42000, "tier": "micro", "niche": "skincare", "avg_reach": 14000, "avg_engagement_rate": 0.065},
    {"id": 6, "handle": "riya.unfiltered", "followers": 28000, "tier": "micro", "niche": "beauty", "avg_reach": 9500, "avg_engagement_rate": 0.070},
    {"id": 7, "handle": "glowgirlpriya", "followers": 65000, "tier": "micro", "niche": "skincare", "avg_reach": 21000, "avg_engagement_rate": 0.050},
    {"id": 8, "handle": "theskincarediaries", "followers": 38000, "tier": "micro", "niche": "skincare", "avg_reach": 13000, "avg_engagement_rate": 0.060},
    {"id": 9, "handle": "fitandflawless_", "followers": 51000, "tier": "micro", "niche": "fitness", "avg_reach": 16000, "avg_engagement_rate": 0.058},
    {"id": 10, "handle": "makeupbymaya", "followers": 22000, "tier": "micro", "niche": "beauty", "avg_reach": 7800, "avg_engagement_rate": 0.060},
    {"id": 11, "handle": "desigirlbeauty", "followers": 47000, "tier": "micro", "niche": "skincare", "avg_reach": 15500, "avg_engagement_rate": 0.050},
    {"id": 12, "handle": "glossyginni", "followers": 33000, "tier": "micro", "niche": "beauty", "avg_reach": 11000, "avg_engagement_rate": 0.062},
    {"id": 13, "handle": "skinspillbyshreya", "followers": 58000, "tier": "micro", "niche": "skincare", "avg_reach": 19000, "avg_engagement_rate": 0.048},
    {"id": 14, "handle": "theglowchronicles", "followers": 71000, "tier": "micro", "niche": "skincare", "avg_reach": 23000, "avg_engagement_rate": 0.045},
    {"id": 15, "handle": "babsactuallybeauty", "followers": 19000, "tier": "micro", "niche": "beauty", "avg_reach": 6800, "avg_engagement_rate": 0.070},
    {"id": 16, "handle": "momlifeandmakeup", "followers": 26000, "tier": "micro", "niche": "mom-and-baby", "avg_reach": 8900, "avg_engagement_rate": 0.060},
    {"id": 17, "handle": "skinbarbynikita", "followers": 63000, "tier": "micro", "niche": "skincare", "avg_reach": 20500, "avg_engagement_rate": 0.050},
    {"id": 18, "handle": "theclearskinclub", "followers": 44000, "tier": "micro", "niche": "skincare", "avg_reach": 14800, "avg_engagement_rate": 0.055},
    {"id": 19, "handle": "glowwithgauri", "followers": 36000, "tier": "micro", "niche": "skincare", "avg_reach": 12000, "avg_engagement_rate": 0.060},
    {"id": 20, "handle": "casualcosmetics", "followers": 14000, "tier": "micro", "niche": "beauty", "avg_reach": 5200, "avg_engagement_rate": 0.072},
]

FEES = {1: 55000, 2: 68000, 3: 72000, 4: 95000, 5: 12000, 6: 9000, 7: 16000, 8: 11000,
        9: 14000, 10: 8000, 11: 13000, 12: 10000, 13: 15000, 14: 18000, 15: 7000,
        16: 9500, 17: 16500, 18: 12500, 19: 10500, 20: 6500}

MIN_REACH = {1: 43000, 2: 56000, 3: 68000, 4: 88000, 5: 11000, 6: 7500, 7: 17000, 8: 10000,
             9: 13000, 10: 6000, 11: 12000, 12: 9000, 13: 15000, 14: 18000, 15: 5500,
             16: 7000, 17: 16000, 18: 12000, 19: 9500, 20: 4000}

FORMAT = {1: "reel", 2: "reel", 3: "reel", 4: "carousel", 5: "story", 6: "reel", 7: "carousel",
          8: "reel", 9: "story", 10: "reel", 11: "carousel", 12: "reel", 13: "reel",
          14: "carousel", 15: "story", 16: "story", 17: "reel", 18: "carousel", 19: "reel", 20: "story"}

# Scenario tag per creator — documents which of the 12 brief problems this post demonstrates.
# "healthy" = should trigger nothing. Some creators carry two scenario tags.
SCENARIOS: dict[int, list[str]] = {
    1: ["healthy"], 2: ["not_posted"], 3: ["posted_late", "suspicious_engagement"],
    4: ["missing_disclosure"], 5: ["healthy"], 6: ["healthy"], 7: ["missing_tag_link"],
    8: ["underperforming"], 9: ["healthy"], 10: ["suspicious_engagement"],
    11: ["negative_sentiment"], 12: ["healthy"], 13: ["deleted_early"],
    14: ["caption_edited", "missing_disclosure"], 15: ["healthy"], 16: ["story_expired"],
    17: ["competitor_post"], 18: ["healthy"], 19: ["viral_winner"], 20: ["healthy"],
}


def build_post(cid: int) -> dict:
    """Builds the post + snapshot + comment rows for one creator's deliverable,
    according to its scenario tag(s)."""
    tags = SCENARIOS[cid]
    avg_reach = CREATORS[cid - 1]["avg_reach"]
    min_reach = MIN_REACH[cid]
    is_story = FORMAT[cid] == "story"
    engagement_rate = CREATORS[cid - 1]["avg_engagement_rate"]

    post: dict = {
        "posted_at": iso(at(1, 10, 0)),
        "caption": COMPLIANT_CAPTION,
        "original_caption": COMPLIANT_CAPTION,
        "caption_edited_at": None,
        # Link stickers are a Story-only IG feature — a reel/carousel can't
        # carry one at all, so defaulting this to 1 on every format (as the
        # old seed did) was factually wrong data hiding rule 4's unconditional
        # link-sticker check. Only stories get it by default now.
        "link_sticker_present": 1 if is_story else 0,
        "permalink": f"https://instagram.com/p/sample-{cid}/",
        "is_story": int(is_story),
        "screenshot_uploaded": 1,
        "deleted_at_day": None,
        "competitor_mentioned_day": None,
    }
    snapshots: list[dict] = []
    comments: list[dict] = []

    final_reach = round(avg_reach * 1.07)  # default: healthy, slightly above own average

    if "not_posted" in tags:
        post["posted_at"] = None
        post["caption"] = None
        post["original_caption"] = None
        post["link_sticker_present"] = 0
        post["screenshot_uploaded"] = 0
        return {"post": post, "snapshots": [], "comments": []}

    if "posted_late" in tags:
        post["posted_at"] = iso(at(1, 20, 0))  # 11h after the 09:00 due time (> 6h threshold)

    if "missing_disclosure" in tags:
        post["caption"] = (
            "New skincare era unlocked ✨ Obsessed with how my skin feels after using "
            "this Vitamin C serum from @glowleaf! #GlowWithGlowLeaf #skincare"
        )
        post["original_caption"] = post["caption"]

    if "missing_tag_link" in tags:
        post["caption"] = (
            "New skincare era unlocked ✨ Obsessed with how my skin feels after using "
            "this serum! #ad #skincare"
        )
        post["original_caption"] = post["caption"]
        post["link_sticker_present"] = 0

    if "underperforming" in tags:
        final_reach = round(min(min_reach * 0.6, avg_reach * 0.5))  # below both thresholds

    if "deleted_early" in tags:
        final_reach = round(avg_reach * 0.95)  # irrelevant once it's gone, but keep it plausible

    if "story_expired" in tags:
        final_reach = round(avg_reach * 0.5)  # only 1 day of data before expiry
        post["screenshot_uploaded"] = 0

    if "competitor_post" in tags:
        post["competitor_mentioned_day"] = 2  # within the 3-day competitor window

    if "viral_winner" in tags:
        final_reach = round(avg_reach * 2.6)  # above the 2.2x viral multiplier

    if "caption_edited" in tags:
        edited_caption = (
            "Okay not sponsored talk but this literally cures acne overnight and I'm never "
            "going back \U0001F60D @glowleaf #GlowWithGlowLeaf"
        )
        post["original_caption"] = COMPLIANT_CAPTION
        post["caption"] = edited_caption
        post["caption_edited_at"] = iso(at(3, 12, 0))

    # --- snapshots -----------------------------------------------------
    if "deleted_early" in tags:
        reach_curve = curve(final_reach, days=4)
        for d, reach in enumerate(reach_curve, start=1):
            likes, cmts, saves, shares = metrics_from_reach(reach, engagement_rate)
            snapshots.append({"day_number": d, "reach": reach, "likes": likes, "comments_count": cmts,
                               "saves": saves, "shares": shares, "still_live": 1})
        last_reach = reach_curve[-1]
        last_likes, last_cmts, last_saves, last_shares = metrics_from_reach(last_reach, engagement_rate)
        for d in range(5, DURATION_DAYS + 1):
            snapshots.append({"day_number": d, "reach": last_reach, "likes": last_likes,
                               "comments_count": last_cmts, "saves": last_saves, "shares": last_shares,
                               "still_live": 0})
    elif "story_expired" in tags:
        reach_curve = curve(final_reach, days=2, start_frac=0.6)
        for d, reach in enumerate(reach_curve, start=1):
            likes, cmts, saves, shares = metrics_from_reach(reach, engagement_rate)
            snapshots.append({"day_number": d, "reach": reach, "likes": likes, "comments_count": cmts,
                               "saves": saves, "shares": shares, "still_live": 1})
    else:
        reach_curve = curve(final_reach)
        for d, reach in enumerate(reach_curve, start=1):
            likes, cmts, saves, shares = metrics_from_reach(reach, engagement_rate)
            snapshots.append({"day_number": d, "reach": reach, "likes": likes, "comments_count": cmts,
                               "saves": saves, "shares": shares, "still_live": 1})

        if "suspicious_engagement" in tags and cid == 3:
            # day-over-day like spike beyond the 4x multiplier, same reach curve
            snapshots[-1]["likes"] = snapshots[-2]["likes"] * 5
        if "suspicious_engagement" in tags and cid == 10:
            # like:comment ratio far below the normal band (bought-likes pattern)
            snapshots[-1]["comments_count"] = max(1, round(snapshots[-1]["likes"] * 0.005))

    # --- comments (sample of actual text, not exhaustive) --------------
    if "negative_sentiment" in tags:
        comments = [
            {"day_number": 5, "author_handle": "user_anu22", "text": "this gave me such a bad rash, careful guys", "language": "en"},
            {"day_number": 5, "author_handle": "priya.k", "text": "yeh toh dhoka hai, paisa barbad ho gaya mera", "language": "hi-en"},
            {"day_number": 6, "author_handle": "sam_writes", "text": "allergy ho gayi mujhe isse, please be careful", "language": "hi-en"},
            {"day_number": 6, "author_handle": "rahul_v", "text": "lagta hai fake reviews hai sab, bekar product", "language": "hi-en"},
            {"day_number": 7, "author_handle": "neha.says", "text": "actually works pretty well for me, no issues", "language": "en"},
            {"day_number": 7, "author_handle": "aman_t", "text": "love the texture, smells amazing too", "language": "en"},
        ]
    else:
        comments = [
            {"day_number": 3, "author_handle": "fan_account_1", "text": "this looks amazing, adding to cart rn", "language": "en"},
            {"day_number": 5, "author_handle": "shreya_m", "text": "skin texture to bohot acha dikh raha hai", "language": "hi-en"},
            {"day_number": 6, "author_handle": "casual_viewer", "text": "little pricey but might try it", "language": "en"},
        ]

    return {"post": post, "snapshots": snapshots, "comments": comments}


def iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Historical campaigns: 6 months, 3-6 past campaigns per creator
# ---------------------------------------------------------------------------

CAMPAIGN_NAME_POOL = [
    "HydraBoost Launch", "SunCare SPF Drive", "Festive Glow Edit", "Retinol Nights",
    "Micellar Clean Push", "Barrier Repair Week", "Summer Skin Reset", "Niacinamide Spotlight",
]

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]

SEVERE_PROBLEM_TAGS = {"not_posted", "deleted_early", "competitor_post"}


def build_history(cid: int) -> list[dict]:
    tags = set(SCENARIOS[cid])
    bias = -0.18 if tags & SEVERE_PROBLEM_TAGS else (-0.08 if "healthy" not in tags else 0.10)
    n = RNG.choice([3, 4, 5, 6])
    months = RNG.sample(MONTHS, k=min(n, len(MONTHS)))
    rows = []
    for month in sorted(months):
        on_time_prob = max(0.1, min(0.95, 0.75 + bias))
        delivered_on_time = 1 if RNG.random() < on_time_prob else 0
        performance_ratio = round(max(0.3, RNG.gauss(1.0 + bias * 0.5, 0.25)), 2)
        flags_count = max(0, round(RNG.gauss(1.0 - bias * 3, 1.0)))
        flags_count = min(flags_count, 4)
        fix_speed_days = round(abs(RNG.gauss(1.2 - bias, 0.6)), 1) if flags_count > 0 else None
        competitor_conflict = 1 if RNG.random() < max(0.02, -bias * 0.5) else 0
        outcome = "completed"
        if delivered_on_time == 0 and flags_count >= 3:
            outcome = RNG.choice(["escalated", "dropped"])
        elif flags_count >= 3:
            outcome = "escalated"
        rows.append({
            "campaign_name": RNG.choice(CAMPAIGN_NAME_POOL),
            "month": month,
            "delivered_on_time": delivered_on_time,
            "performance_ratio": performance_ratio,
            "flags_count": flags_count,
            "fix_speed_days": fix_speed_days,
            "competitor_conflict": competitor_conflict,
            "outcome": outcome,
        })
    return rows


def seed(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = get_connection()
    init_schema(conn)

    # Wipe any existing campaign data (idempotent reseed without --reset too)
    for table in ["decisions", "flags", "comments", "post_snapshots", "posts",
                   "deliverables", "historical_campaigns", "creators", "campaigns", "brands"]:
        conn.execute(f"DELETE FROM {table}")

    conn.execute("INSERT INTO brands (id, name, product) VALUES (1, 'GlowLeaf', 'Vitamin C Serum')")
    conn.execute(
        "INSERT INTO campaigns (id, brand_id, name, start_date, duration_days, required_disclosure, "
        "required_tag, required_hashtag, requires_link_sticker, banned_claims) VALUES "
        "(1, 1, 'GlowLeaf Vitamin C Serum Launch', ?, ?, ?, ?, ?, 1, ?)",
        (iso(CAMPAIGN_START), DURATION_DAYS, REQUIRED_DISCLOSURE, REQUIRED_TAG, REQUIRED_HASHTAG,
         json.dumps(BANNED_CLAIMS)),
    )

    for c in CREATORS:
        conn.execute(
            "INSERT INTO creators (id, handle, followers, tier, niche, avg_reach, avg_engagement_rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (c["id"], c["handle"], c["followers"], c["tier"], c["niche"], c["avg_reach"], c["avg_engagement_rate"]),
        )

    for cid in range(1, 21):
        override = DELIVERABLE_OVERRIDES.get(cid, {})
        waived_notes = override.get("waived_notes")
        conn.execute(
            "INSERT INTO deliverables (id, campaign_id, creator_id, format, fee, promised_date, min_reach, "
            "required_disclosure, required_tag, required_hashtag, requires_link_sticker, "
            "deal_type, barter_value, bonus_threshold, bonus_amount, waived_notes) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, cid, FORMAT[cid],
             override.get("fee", FEES[cid]), iso(at(1, 9, 0)), override.get("min_reach", MIN_REACH[cid]),
             override.get("required_disclosure"), override.get("required_tag"), override.get("required_hashtag"),
             override.get("requires_link_sticker"),
             override.get("deal_type", "paid"), override.get("barter_value"),
             override.get("bonus_threshold"), override.get("bonus_amount"),
             json.dumps(waived_notes) if waived_notes else None),
        )

        built = build_post(cid)
        p = built["post"]
        conn.execute(
            "INSERT INTO posts (id, deliverable_id, posted_at, caption, original_caption, caption_edited_at, "
            "link_sticker_present, permalink, is_story, screenshot_uploaded, deleted_at_day, competitor_mentioned_day) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, cid, p["posted_at"], p["caption"], p["original_caption"], p["caption_edited_at"],
             p["link_sticker_present"], p["permalink"], p["is_story"], p["screenshot_uploaded"],
             p["deleted_at_day"], p["competitor_mentioned_day"]),
        )
        for s in built["snapshots"]:
            conn.execute(
                "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, still_live) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, s["day_number"], s["reach"], s["likes"], s["comments_count"], s["saves"], s["shares"], s["still_live"]),
            )
        for cm in built["comments"]:
            conn.execute(
                "INSERT INTO comments (post_id, day_number, author_handle, text, language) VALUES (?, ?, ?, ?, ?)",
                (cid, cm["day_number"], cm["author_handle"], cm["text"], cm["language"]),
            )

        for h in build_history(cid):
            conn.execute(
                "INSERT INTO historical_campaigns (creator_id, campaign_name, month, delivered_on_time, "
                "performance_ratio, flags_count, fix_speed_days, competitor_conflict, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, h["campaign_name"], h["month"], h["delivered_on_time"], h["performance_ratio"],
                 h["flags_count"], h["fix_speed_days"], h["competitor_conflict"], h["outcome"]),
            )

    # Creator 1's real deal is a package — "1 reel + 2 stories" — not the single
    # post the old one-deliverable-per-creator assumption could represent.
    # Demonstrates that a creator's rolled-up status can go to "Needs a look"
    # (via rule 10 on the second story, once its 24h proof window passes) even
    # while their own reel (post id 1) stays clean — the exact case the old
    # unordered .fetchone() in dashboard.py/reliability.py would have hidden
    # by silently picking just one of the three.
    creator1_avg_reach = CREATORS[0]["avg_reach"]
    creator1_engagement_rate = CREATORS[0]["avg_engagement_rate"]
    extra_deliverables = [
        {"id": 21, "screenshot_uploaded": 1},  # healthy story
        {"id": 22, "screenshot_uploaded": 0},  # no proof uploaded -> rule 10 fires once 24h have passed
    ]
    for extra in extra_deliverables:
        did = extra["id"]
        conn.execute(
            "INSERT INTO deliverables (id, campaign_id, creator_id, format, fee, promised_date, min_reach) "
            "VALUES (?, 1, 1, 'story', 6000, ?, 9000)",
            (did, iso(at(1, 9, 0))),
        )
        reach = round(creator1_avg_reach * 0.3)
        likes, cmts, saves, shares = metrics_from_reach(reach, creator1_engagement_rate)
        conn.execute(
            "INSERT INTO posts (id, deliverable_id, posted_at, caption, original_caption, caption_edited_at, "
            "link_sticker_present, permalink, is_story, screenshot_uploaded, deleted_at_day, competitor_mentioned_day) "
            "VALUES (?, ?, ?, NULL, NULL, NULL, 1, ?, 1, ?, NULL, NULL)",
            (did, did, iso(at(1, 10, 0)), f"https://instagram.com/stories/sample-{did}/", extra["screenshot_uploaded"]),
        )
        conn.execute(
            "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, still_live) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, 1)",
            (did, reach, likes, cmts, saves, shares),
        )

    set_state(conn, "current_day", str(DURATION_DAYS))
    set_state(conn, "ai_enabled", "1")

    conn.commit()
    conn.close()
    print(f"Seeded {DB_PATH} — 20 creators, 1 live campaign (20 posts), 6 months of history.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete the existing DB file first")
    args = parser.parse_args()
    seed(reset=args.reset)
