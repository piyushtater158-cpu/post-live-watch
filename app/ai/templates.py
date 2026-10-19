"""Template/keyword fallback text — used when AI is off, no API key is set,
or the OpenRouter call fails. The app must work end-to-end on these alone.
"""

from __future__ import annotations


def underperform_explanation(creator_handle: str, reach: int, min_reach: int, avg_reach: float) -> str:
    gap_vs_promise = round((1 - reach / min_reach) * 100) if min_reach else 0
    return (
        f"@{creator_handle}'s post reached {reach} ({gap_vs_promise}% below the promised {min_reach}) "
        f"and under their own average of {avg_reach:.0f}. Likely cause: posting time, format mismatch, "
        f"or algorithm reach drop — review timing and creative before deciding next steps."
    )


def sentiment_summary(matched_comments: list[str]) -> dict:
    return {
        "summary": f"{len(matched_comments)} comment(s) matched negative keywords (keyword-match mode — AI is off).",
        "clusters": ["keyword match (AI off)"] if matched_comments else [],
    }


def paraphrase_check_unavailable() -> str | None:
    return None  # keyword-list match only; no paraphrase detection without AI


def boost_suggestion(creator_handle: str, multiplier: float, deal_type: str = "paid") -> str:
    if deal_type == "affiliate":
        return (
            f"@{creator_handle}'s post is performing {multiplier:.1f}x their average. "
            f"Suggested action: push their affiliate link/code harder while it's hot — this is an affiliate deal, not paid media."
        )
    return (
        f"@{creator_handle}'s post is performing {multiplier:.1f}x their average. "
        f"Suggested action: consider a paid boost or add to brand whitelisting while it's hot."
    )


def nudge_message(creator_handle: str, rule_name: str, reason: str) -> str:
    return (
        f"Hi {creator_handle}! Quick note on the GlowLeaf post — we noticed: {reason} "
        f"Could you take a look and fix this when you get a chance? Thanks so much! 🙏"
    )


def brand_alert_message(creator_handle: str, rule_name: str, reason: str) -> str:
    return f"Heads up — {creator_handle}'s post has an issue flagged as '{rule_name}': {reason}"


def brand_daily_report(day: int, duration: int, live_count: int, due_count: int,
                        total_reach: int, promised_reach: int, act_now: int, needs_look: int, ok: int) -> str:
    return (
        f"Day {day} of {duration} — GlowLeaf Vitamin C Serum Launch\n\n"
        f"Posts live: {live_count}/{due_count}. Total reach so far: {total_reach:,} "
        f"(promised: {promised_reach:,}).\n"
        f"Status: {act_now} need action now, {needs_look} need a look, {ok} are on track.\n"
        f"This is a template summary (AI is off) — turn AI on for a narrative version."
    )
