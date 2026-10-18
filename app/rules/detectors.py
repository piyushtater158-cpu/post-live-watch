"""The 12 post-live detectors. Every detector is a pure function:
(PostContext, thresholds) -> flag dict | None.

No AI anywhere in this file — that's the point. Each detector returns a
plain dict with a transparent, reproducible reason. AI (app/ai/provider.py)
only ever adds language on top of a flag that already fired here; it never
decides whether something fired.
"""

from __future__ import annotations

from datetime import timedelta

from .context import PostContext

NEGATIVE = "negative"
POSITIVE = "positive"


def _sev(thresholds: dict, rule_id: int) -> int:
    return thresholds["rule_severity"][rule_id]


def rule_1_not_posted(ctx: PostContext, t: dict) -> dict | None:
    if ctx.posted_at is not None:
        return None
    grace = t["not_posted_grace_days"]
    if ctx.current_day <= ctx.due_day + grace:
        return None
    return {
        "rule_id": 1, "rule_name": "Not posted", "polarity": NEGATIVE,
        "severity": _sev(t, 1),
        "reason": f"No post by day {ctx.due_day} + {grace}-day grace (now day {ctx.current_day}).",
        "evidence": {"due_day": ctx.due_day, "grace_days": grace, "current_day": ctx.current_day},
    }


def rule_2_posted_late(ctx: PostContext, t: dict) -> dict | None:
    if ctx.posted_at is None:
        return None
    late_hours = (ctx.posted_at - ctx.promised_date).total_seconds() / 3600
    threshold = t["posted_late_hours"]
    if late_hours <= threshold:
        return None
    return {
        "rule_id": 2, "rule_name": "Posted late", "polarity": NEGATIVE,
        "severity": _sev(t, 2),
        "reason": f"Posted {late_hours:.1f}h after the promised time (threshold {threshold}h).",
        "evidence": {"late_hours": round(late_hours, 1), "threshold_hours": threshold},
    }


def rule_3_missing_disclosure(ctx: PostContext, t: dict) -> dict | None:
    if not ctx.caption:
        return None
    cap = ctx.caption.lower()
    has_disclosure = "#ad" in cap or "paid partnership" in cap
    if has_disclosure:
        return None
    return {
        "rule_id": 3, "rule_name": "Missing disclosure", "polarity": NEGATIVE,
        "severity": _sev(t, 3),
        "reason": f"Caption has no {ctx.required_disclosure} label.",
        "evidence": {"caption": ctx.caption},
    }


def rule_4_missing_tag_link_hashtag(ctx: PostContext, t: dict) -> dict | None:
    if not ctx.caption:
        return None
    cap = ctx.caption.lower()
    missing = []
    if ctx.required_tag.lower() not in cap:
        missing.append(f"tag {ctx.required_tag}")
    if ctx.required_hashtag.lower() not in cap:
        missing.append(f"hashtag {ctx.required_hashtag}")
    if not ctx.link_sticker_present:
        missing.append("link sticker")
    if not missing:
        return None
    return {
        "rule_id": 4, "rule_name": "Missing/wrong brand tag, link or hashtag", "polarity": NEGATIVE,
        "severity": _sev(t, 4),
        "reason": "Missing: " + ", ".join(missing) + ".",
        "evidence": {"missing": missing, "caption": ctx.caption},
    }


def rule_5_underperforming(ctx: PostContext, t: dict) -> dict | None:
    latest = ctx.latest_snapshot
    if latest is None:
        return None
    reach = latest["reach"]
    promise_cutoff = t["underperform_pct_of_promise"] * ctx.min_reach
    avg_cutoff = t["underperform_pct_of_creator_avg"] * ctx.creator_avg_reach
    if reach < promise_cutoff and reach < avg_cutoff:
        return {
            "rule_id": 5, "rule_name": "Underperforming", "polarity": NEGATIVE,
            "severity": _sev(t, 5),
            "reason": (
                f"Reach {reach} is below {t['underperform_pct_of_promise']*100:.0f}% of the promised "
                f"{ctx.min_reach} and below {t['underperform_pct_of_creator_avg']*100:.0f}% of this "
                f"creator's average ({ctx.creator_avg_reach:.0f})."
            ),
            "evidence": {"reach": reach, "min_reach": ctx.min_reach, "creator_avg_reach": ctx.creator_avg_reach,
                         "promise_cutoff": round(promise_cutoff), "avg_cutoff": round(avg_cutoff)},
        }
    return None


def rule_6_suspicious_engagement(ctx: PostContext, t: dict) -> dict | None:
    latest = ctx.latest_snapshot
    if latest is None or latest["likes"] <= 0:
        return None
    ratio = latest["comments_count"] / latest["likes"]
    ratio_min, ratio_max = t["engagement_ratio_min"], t["engagement_ratio_max"]
    ratio_bad = ratio < ratio_min or ratio > ratio_max

    spike = False
    spike_detail = None
    prev = ctx.previous_snapshot
    if prev is not None and prev["likes"] > 0:
        growth = latest["likes"] / prev["likes"]
        if growth > t["engagement_spike_multiplier"]:
            spike = True
            spike_detail = round(growth, 2)

    if not ratio_bad and not spike:
        return None

    reasons = []
    if ratio_bad:
        reasons.append(f"comment:like ratio {ratio:.3f} is outside the normal [{ratio_min}, {ratio_max}] band")
    if spike:
        reasons.append(f"likes jumped {spike_detail}x day-over-day (threshold {t['engagement_spike_multiplier']}x)")
    return {
        "rule_id": 6, "rule_name": "Suspicious engagement", "polarity": NEGATIVE,
        "severity": _sev(t, 6),
        "reason": "; ".join(reasons).capitalize() + ".",
        "evidence": {"ratio": round(ratio, 4), "spike_multiplier": spike_detail},
    }


def rule_7_negative_sentiment(ctx: PostContext, t: dict) -> dict | None:
    if not ctx.comments:
        return None
    keywords = [k.lower() for k in t["negative_keywords"]]
    matched = [c for c in ctx.comments if any(k in c["text"].lower() for k in keywords)]
    count = len(matched)
    ratio = count / len(ctx.comments)
    if count < t["sentiment_negative_keyword_count"] and ratio < t["sentiment_negative_ratio"]:
        return None
    return {
        "rule_id": 7, "rule_name": "Negative sentiment spike", "polarity": NEGATIVE,
        "severity": _sev(t, 7),
        "reason": f"{count} of {len(ctx.comments)} sampled comments hit the negative keyword list.",
        "evidence": {"matched_comments": [c["text"] for c in matched], "count": count, "ratio": round(ratio, 2)},
    }


def rule_8_deleted_early(ctx: PostContext, t: dict) -> dict | None:
    seen_live = False
    for s in ctx.snapshots:
        if s["still_live"]:
            seen_live = True
            continue
        if seen_live and not s["still_live"] and s["day_number"] < ctx.duration_days:
            return {
                "rule_id": 8, "rule_name": "Deleted or archived early", "polarity": NEGATIVE,
                "severity": _sev(t, 8),
                "reason": f"Post went missing on day {s['day_number']}, before the campaign's day {ctx.duration_days} end.",
                "evidence": {"disappeared_day": s["day_number"], "campaign_end_day": ctx.duration_days},
            }
    return None


def rule_9_caption_edited_off_brief(ctx: PostContext, t: dict) -> dict | None:
    if ctx.caption_edited_at is None or ctx.caption == ctx.original_caption:
        return None
    if ctx.campaign_start + timedelta(days=ctx.current_day) < ctx.caption_edited_at:
        return None
    cap = (ctx.caption or "").lower()
    hit = [phrase for phrase in ctx.banned_claims if phrase.lower() in cap]
    if not hit:
        return None
    return {
        "rule_id": 9, "rule_name": "Caption edited post-approval / off-brief claim", "polarity": NEGATIVE,
        "severity": _sev(t, 9),
        "reason": f"Caption was edited after approval and now contains banned claim(s): {', '.join(hit)}.",
        "evidence": {"original_caption": ctx.original_caption, "current_caption": ctx.caption, "banned_hits": hit},
    }


def rule_10_story_expired_no_proof(ctx: PostContext, t: dict) -> dict | None:
    if not ctx.is_story or ctx.posted_at is None or ctx.screenshot_uploaded:
        return None
    window_hours = t["story_proof_window_hours"]
    age_hours = (ctx.as_of - ctx.posted_at).total_seconds() / 3600
    if age_hours <= window_hours:
        return None
    return {
        "rule_id": 10, "rule_name": "Story expired without proof", "polarity": NEGATIVE,
        "severity": _sev(t, 10),
        "reason": f"Story is {age_hours:.0f}h old (past the {window_hours}h window) with no screenshot/insights uploaded.",
        "evidence": {"age_hours": round(age_hours, 1), "window_hours": window_hours},
    }


def rule_11_competitor_post(ctx: PostContext, t: dict) -> dict | None:
    if ctx.competitor_mentioned_day is None or ctx.competitor_mentioned_day > ctx.current_day:
        return None
    window = t["competitor_window_days"]
    if abs(ctx.competitor_mentioned_day - ctx.due_day) > window:
        return None
    return {
        "rule_id": 11, "rule_name": "Competitor post", "polarity": NEGATIVE,
        "severity": _sev(t, 11),
        "reason": f"Creator posted a competitor mention on day {ctx.competitor_mentioned_day}, within the {window}-day window.",
        "evidence": {"competitor_mentioned_day": ctx.competitor_mentioned_day, "window_days": window},
    }


def rule_12_viral_winner(ctx: PostContext, t: dict) -> dict | None:
    latest = ctx.latest_snapshot
    if latest is None or ctx.creator_avg_reach <= 0:
        return None
    multiplier = latest["reach"] / ctx.creator_avg_reach
    if multiplier < t["viral_multiplier"]:
        return None
    return {
        "rule_id": 12, "rule_name": "Viral winner", "polarity": POSITIVE,
        "severity": _sev(t, 12),
        "reason": f"Reach is {multiplier:.1f}x this creator's average ({ctx.creator_avg_reach:.0f}) — consider a boost or whitelisting.",
        "evidence": {"reach": latest["reach"], "creator_avg_reach": ctx.creator_avg_reach, "multiplier": round(multiplier, 2)},
    }


ALL_DETECTORS = [
    rule_1_not_posted, rule_2_posted_late, rule_3_missing_disclosure, rule_4_missing_tag_link_hashtag,
    rule_5_underperforming, rule_6_suspicious_engagement, rule_7_negative_sentiment, rule_8_deleted_early,
    rule_9_caption_edited_off_brief, rule_10_story_expired_no_proof, rule_11_competitor_post, rule_12_viral_winner,
]
