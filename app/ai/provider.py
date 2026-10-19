"""The single AI-calling function, plus the handful of task wrappers that use
it. Every task function has a template fallback (app/ai/templates.py) and is
called the same way whether AI is on or off — callers never branch on the
toggle themselves, this module does.

Provider: OpenRouter (https://openrouter.ai), FREE models only. The model
list comes from OPENROUTER_MODELS (comma-separated, in preference order) and
is tried in groups of 3 via OpenRouter's `models` fallback array.
"""

from __future__ import annotations

import os
import threading
import time

import httpx

from . import templates as tpl

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT = 15.0

# Preference order for this app's short drafting/classification tasks (incl.
# Hinglish): fast general instruct models first, the openrouter/free router last.
DEFAULT_FREE_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-26b-a4b-it:free",
    "openrouter/free",
)
FREE_ROUTER = "openrouter/free"
MODELS_PER_REQUEST = 3  # OpenRouter rejects a `models` array longer than this
RATE_LIMIT_COOLDOWN_S = 60.0
CACHE_MAX = 512

_cache: dict[tuple, str] = {}
_inflight: dict[tuple, threading.Event] = {}
_lock = threading.Lock()
_cooldown_until = 0.0


def is_free_model(model_id: str) -> bool:
    return model_id.endswith(":free") or model_id == FREE_ROUTER


def free_models() -> list[str]:
    """The configured model list with anything that isn't a free variant
    dropped — the account has no paid budget, so a paid id must never be sent."""
    raw = os.environ.get("OPENROUTER_MODELS", "")
    configured = [m.strip() for m in raw.split(",") if m.strip()] or list(DEFAULT_FREE_MODELS)
    return [m for m in configured if is_free_model(m)]


def _request(api_key: str, models: list[str], system_prompt: str, user_prompt: str,
             max_tokens: int, temperature: float) -> str | None:
    global _cooldown_until
    resp = httpx.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "models": models,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Reasoning tokens would eat max_tokens and add latency for one-sentence tasks.
            "reasoning": {"enabled": False},
            # Second guard behind the :free allowlist — OpenRouter refuses any endpoint that costs money.
            "provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0}},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 429:
        # Account-level limits (free-models-per-min / per-day) pause AI app-wide;
        # a 429 relayed from one busy upstream provider just moves on to the next group.
        try:
            message = str(resp.json().get("error", {}).get("message", ""))
        except ValueError:
            message = ""
        if "rate limit exceeded" in message.lower():
            reset_ms = resp.headers.get("X-RateLimit-Reset")
            reset_at = int(reset_ms) / 1000 if reset_ms and reset_ms.isdigit() else 0
            _cooldown_until = max(time.time() + RATE_LIMIT_COOLDOWN_S, reset_at)
        return None
    resp.raise_for_status()
    content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    return content or None


def call_ai(system_prompt: str, user_prompt: str, max_tokens: int = 300, temperature: float = 0.4) -> str | None:
    """Returns the model's text, or None if AI is off / unconfigured / the call fails.
    This is the ONE place that talks to an LLM provider in this app. Answers are
    cached per prompt (free models allow ~50 requests/day), concurrent identical
    calls share one request, and after a rate-limit response every call falls
    straight back to templates until the limit resets."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    models = free_models()
    if not api_key or not models or time.time() < _cooldown_until:
        return None

    key = (system_prompt, user_prompt, max_tokens, temperature)
    with _lock:
        if key in _cache:
            return _cache[key]
        waiter = _inflight.get(key)
        if waiter is None:
            _inflight[key] = threading.Event()
    if waiter is not None:
        waiter.wait(REQUEST_TIMEOUT * 2 + 5)
        return _cache.get(key)

    text = None
    try:
        for i in range(0, len(models), MODELS_PER_REQUEST):
            if time.time() < _cooldown_until:
                break
            try:
                text = _request(api_key, models[i:i + MODELS_PER_REQUEST], system_prompt, user_prompt,
                                max_tokens, temperature)
            except Exception:
                text = None  # network, auth, provider error, bad response — try the next group
            if text:
                break
    finally:
        with _lock:
            if text:
                if len(_cache) >= CACHE_MAX:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = text
            _inflight.pop(key).set()
    return text


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


def suggest_boost(ai_enabled: bool, creator_handle: str, multiplier: float, niche: str, deal_type: str = "paid") -> str:
    if ai_enabled:
        deal_hint = (
            "This is an affiliate deal, so lean on pushing the affiliate link/code rather than a paid boost."
            if deal_type == "affiliate" else ""
        )
        text = call_ai(
            "You are a performance marketing strategist. In one sentence, suggest a concrete boost "
            "or whitelisting action for a viral organic post.",
            f"@{creator_handle} ({niche}) is at {multiplier:.1f}x their average reach. {deal_hint}".strip(),
        )
        if text:
            return text
    return tpl.boost_suggestion(creator_handle, multiplier, deal_type)


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
