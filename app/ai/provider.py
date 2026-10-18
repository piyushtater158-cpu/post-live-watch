"""The single AI-calling function, plus the handful of task wrappers that use
it. Every task function has a template fallback (app/ai/templates.py) and is
called the same way whether AI is on or off — callers never branch on the
toggle themselves, this module does.

Provider: OpenRouter (https://openrouter.ai), one chat-completions call,
model selectable via the OPENROUTER_MODEL env var so it can be swapped
without touching code.
"""

from __future__ import annotations

import os

import httpx

from . import templates as tpl

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"  # placeholder default; override via OPENROUTER_MODEL
REQUEST_TIMEOUT = 15.0


def call_ai(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str | None:
    """Returns the model's text, or None if AI is off / unconfigured / the call fails.
    This is the ONE place that talks to an LLM provider in this app."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.4,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None  # any failure (network, auth, rate limit, bad response) falls back to templates


def explain_underperformance(ai_enabled: bool, creator_handle: str, reach: int, min_reach: int,
                              avg_reach: float, niche: str, format_: str) -> str:
    if ai_enabled:
        text = call_ai(
            "You are a sharp influencer-marketing analyst. In one or two sentences, give the "
            "most likely cause of an underperforming post and one concrete next step. Be specific, no fluff.",
            f"Creator @{creator_handle} ({niche} niche) posted a {format_}. Reach was {reach}, "
            f"promised minimum was {min_reach}, their average reach is {avg_reach:.0f}.",
        )
        if text:
            return text
    return tpl.underperform_explanation(creator_handle, reach, min_reach, avg_reach)


def classify_sentiment(ai_enabled: bool, comments: list[dict]) -> dict:
    matched_texts = [c["text"] for c in comments]
    if ai_enabled and matched_texts:
        joined = "\n".join(f"- {t}" for t in matched_texts)
        text = call_ai(
            "You read Hindi-English (Hinglish) social comments, including sarcasm. "
            "Summarize the complaint pattern in one sentence, then list 2-4 short complaint cluster labels, "
            "comma separated, after a '|' character. Example: 'Users report skin irritation. | irritation, trust, price'",
            f"Comments:\n{joined}",
        )
        if text and "|" in text:
            summary, _, clusters_raw = text.partition("|")
            clusters = [c.strip() for c in clusters_raw.split(",") if c.strip()]
            return {"summary": summary.strip(), "clusters": clusters}
        if text:
            return {"summary": text, "clusters": []}
    return tpl.sentiment_summary(matched_texts)


def detect_paraphrased_claim(ai_enabled: bool, original_caption: str | None, current_caption: str | None,
                              banned_claims: list[str]) -> str | None:
    """Supplementary note only — never a new flag. The deterministic rule_9
    (literal banned-phrase match) remains the source of truth; this adds
    judgment for edits that dodge the literal keyword list via paraphrase."""
    if not ai_enabled or not current_caption or current_caption == original_caption:
        return tpl.paraphrase_check_unavailable()
    text = call_ai(
        "You check influencer captions against a brand's banned-claims list for paraphrased "
        "(not literal) violations. If you find one, name it in one short sentence. If not, reply exactly: NONE.",
        f"Banned claims: {', '.join(banned_claims)}\nOriginal caption: {original_caption}\n"
        f"Current caption: {current_caption}",
    )
    if text and text.strip().upper() != "NONE":
        return text
    return None


def suggest_boost(ai_enabled: bool, creator_handle: str, multiplier: float, niche: str) -> str:
    if ai_enabled:
        text = call_ai(
            "You are a performance marketing strategist. In one sentence, suggest a concrete boost "
            "or whitelisting action for a viral organic post.",
            f"@{creator_handle} ({niche}) is at {multiplier:.1f}x their average reach.",
        )
        if text:
            return text
    return tpl.boost_suggestion(creator_handle, multiplier)


def generate_nudge_message(ai_enabled: bool, creator_handle: str, rule_name: str, reason: str) -> str:
    if ai_enabled:
        text = call_ai(
            "Write a short, warm, professional WhatsApp-style message from an account manager to a "
            "creator, asking them to fix a flagged issue with their sponsored post. 2-3 sentences, friendly, no corporate jargon.",
            f"Creator: @{creator_handle}. Issue ({rule_name}): {reason}",
        )
        if text:
            return text
    return tpl.nudge_message(creator_handle, rule_name, reason)


def generate_brand_alert(ai_enabled: bool, creator_handle: str, rule_name: str, reason: str) -> str:
    if ai_enabled:
        text = call_ai(
            "Write a one-sentence, calm, factual alert for a brand client about a flagged influencer post issue.",
            f"Creator: @{creator_handle}. Issue ({rule_name}): {reason}",
        )
        if text:
            return text
    return tpl.brand_alert_message(creator_handle, rule_name, reason)


def generate_brand_daily_report(ai_enabled: bool, day: int, duration: int, live_count: int, due_count: int,
                                 total_reach: int, promised_reach: int, act_now: int, needs_look: int,
                                 ok: int, highlights: list[str], issues: list[str]) -> str:
    if ai_enabled:
        text = call_ai(
            "Write a short, confident daily campaign status update for a brand client. 3-5 sentences: "
            "what went live, a highlight, any issues and what's being done about them. No corporate fluff.",
            f"Day {day}/{duration}. Posts live: {live_count}/{due_count}. Reach: {total_reach} of {promised_reach} promised. "
            f"{act_now} act-now flags, {needs_look} need-a-look, {ok} on track. "
            f"Highlights: {'; '.join(highlights) or 'none yet'}. Issues: {'; '.join(issues) or 'none'}.",
            max_tokens=250,
        )
        if text:
            return text
    return tpl.brand_daily_report(day, duration, live_count, due_count, total_reach, promised_reach,
                                   act_now, needs_look, ok)
