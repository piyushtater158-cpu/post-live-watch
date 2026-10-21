"""The single AI-calling function, plus the handful of task wrappers that use
it. Every task function has a template fallback (app/ai/templates.py) and is
called the same way whether AI is on or off — callers never branch on the
toggle themselves, this module does.

Provider: OpenRouter (https://openrouter.ai), FREE models only. The model
list comes from OPENROUTER_MODELS (comma-separated, in preference order) and
is tried in groups of 3 via OpenRouter's `models` fallback array.
"""

from __future__ import annotations

import json
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
                              avg_reach: float, niche: str, format_: str, avg_reach_source: str | None = None) -> str:
    # avg_reach_source == 'estimated' (app/intake.py) means this isn't a measured
    # number — the narrative must not state it as fact any more confidently than
    # rule_5's own reason text does (app/rules/detectors.py).
    avg_caveat = " (estimated from follower count, not measured)" if avg_reach_source == "estimated" else ""
    if ai_enabled:
        text = call_ai(
            "You are a sharp influencer-marketing analyst. In one or two sentences, give the "
            "most likely cause of an underperforming post and one concrete next step. Be specific, no fluff.",
            f"Creator @{creator_handle} ({niche} niche) posted a {format_}. Reach was {reach}, "
            f"promised minimum was {min_reach}, their average reach is {avg_reach:.0f}{avg_caveat}.",
        )
        if text:
            return text
    return tpl.underperform_explanation(creator_handle, reach, min_reach, avg_reach, avg_reach_source)


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


def generate_nudge_message(ai_enabled: bool, creator_handle: str, rule_name: str, reason: str,
                            brand_name: str = "the brand") -> str:
    if ai_enabled:
        text = call_ai(
            "Write a short, warm, professional WhatsApp-style message from an account manager to a "
            "creator, asking them to fix a flagged issue with their sponsored post. 2-3 sentences, friendly, no corporate jargon.",
            f"Brand: {brand_name}. Creator: @{creator_handle}. Issue ({rule_name}): {reason}",
        )
        if text:
            return text
    return tpl.nudge_message(creator_handle, rule_name, reason, brand_name)


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
                                 ok: int, highlights: list[str], issues: list[str],
                                 campaign_name: str = "This campaign") -> str:
    if ai_enabled:
        text = call_ai(
            "Write a short, confident daily campaign status update for a brand client. 3-5 sentences: "
            "what went live, a highlight, any issues and what's being done about them. No corporate fluff.",
            f"Campaign: {campaign_name}. Day {day}/{duration}. Posts live: {live_count}/{due_count}. "
            f"Reach: {total_reach} of {promised_reach} promised. "
            f"{act_now} act-now flags, {needs_look} need-a-look, {ok} on track. "
            f"Highlights: {'; '.join(highlights) or 'none yet'}. Issues: {'; '.join(issues) or 'none'}.",
            max_tokens=250,
        )
        if text:
            return text
    return tpl.brand_daily_report(day, duration, live_count, due_count, total_reach, promised_reach,
                                   act_now, needs_look, ok, campaign_name)


_BRIEF_SYSTEM_PROMPT = """You convert an account manager's shorthand note about a signed \
creator deal into ONE strict JSON object. Extract only what the note states — never invent \
facts it doesn't contain.

Output exactly one JSON object, no prose, no markdown code fences, matching this shape:
{
  "creator": {"handle": str|null, "raw_name": str|null, "followers": number|null,
              "tier": "mid"|"micro"|null, "niche": str|null},
  "deliverables": [
    {"format": "reel"|"carousel"|"story", "deal_type": "paid"|"barter"|"affiliate"|"paid_plus_bonus",
     "fee": number|null, "barter_value": number|null, "bonus_threshold": number|null, "bonus_amount": number|null,
     "min_reach": number|null, "min_reach_explicitly_none": bool,
     "due_in_days": number|null,
     "required_tag": str|null, "required_hashtag": str|null, "requires_link_sticker": bool|null,
     "waived_notes": {"required_tag"?: str, "required_hashtag"?: str, "requires_link_sticker"?: str}}
  ]
}

Null semantics (read carefully, this is the entire point of the system):
- null on required_tag/required_hashtag/requires_link_sticker means "the note doesn't mention
  this — inherit whatever the campaign already requires."
- "" (empty string) on required_tag/required_hashtag, or false on requires_link_sticker, means
  "the note says this was negotiated away." Whenever you emit that, you MUST also add a matching
  waived_notes entry quoting the note's stated reason (or "Waived at intake — reason not stated"
  if none was given).
- min_reach_explicitly_none=true ONLY when the note explicitly says no reach guarantee/minimum
  was promised. If the note simply never mentions reach, leave min_reach null and
  min_reach_explicitly_none false — do not assume absence means "explicitly waived."

Hard prohibitions:
- NEVER output avg_reach, avg_engagement_rate, or any performance/reach number that is not a
  literal min_reach or fee figure stated in the note. Those are estimated by the server from
  follower count, never by you.
- NEVER output required_disclosure at all, and never imply it was waived — disclosure can't be
  waived through this flow.
- NEVER compute a calendar date. Only emit due_in_days as an integer day offset; the server does
  date arithmetic against the campaign's own calendar.

Example 1 — "Signed Priya for 2 reels + 1 story, barter deal worth ₹5k product, no reach \
guarantee, she's skipping our campaign hashtag due to an exclusivity clause, due in 3 days" ->
{"creator": {"handle": null, "raw_name": "Priya", "followers": null, "tier": null, "niche": null},
 "deliverables": [
   {"format": "reel", "deal_type": "barter", "fee": null, "barter_value": 5000, "bonus_threshold": null,
    "bonus_amount": null, "min_reach": null, "min_reach_explicitly_none": true, "due_in_days": 3,
    "required_tag": null, "required_hashtag": "", "requires_link_sticker": null,
    "waived_notes": {"required_hashtag": "Exclusivity clause with a rival campaign."}},
   {"format": "reel", "deal_type": "barter", "fee": null, "barter_value": 5000, "bonus_threshold": null,
    "bonus_amount": null, "min_reach": null, "min_reach_explicitly_none": true, "due_in_days": 3,
    "required_tag": null, "required_hashtag": "", "requires_link_sticker": null,
    "waived_notes": {"required_hashtag": "Exclusivity clause with a rival campaign."}},
   {"format": "story", "deal_type": "barter", "fee": null, "barter_value": 5000, "bonus_threshold": null,
    "bonus_amount": null, "min_reach": null, "min_reach_explicitly_none": true, "due_in_days": 3,
    "required_tag": null, "required_hashtag": "", "requires_link_sticker": null,
    "waived_notes": {"required_hashtag": "Exclusivity clause with a rival campaign."}}
 ]}

Example 2 — "renew @glow_with_meera for one more reel, ₹55k, 40k min reach" ->
{"creator": {"handle": "glow_with_meera", "raw_name": null, "followers": null, "tier": null, "niche": null},
 "deliverables": [
   {"format": "reel", "deal_type": "paid", "fee": 55000, "barter_value": null, "bonus_threshold": null,
    "bonus_amount": null, "min_reach": 40000, "min_reach_explicitly_none": false, "due_in_days": null,
    "required_tag": null, "required_hashtag": null, "requires_link_sticker": null, "waived_notes": {}}
 ]}"""


_CAMPAIGN_BRIEF_SYSTEM_PROMPT = """You convert an account manager's note about an entire influencer campaign \
— brand-new or already running — into ONE strict JSON object covering the campaign itself and every \
creator deal mentioned. Extract only what the note states — never invent facts it doesn't contain.

Output exactly one JSON object, no prose, no markdown code fences, matching this shape:
{
  "campaign": {
    "name": str|null, "brand_name": str|null, "product": str|null,
    "duration_days": number|null, "days_running": number|null,
    "required_disclosure": str|null, "required_tag": str|null, "required_hashtag": str|null,
    "requires_link_sticker": bool|null, "banned_claims": [str]|null
  },
  "creators": [
    {"creator": {"handle": str|null, "raw_name": str|null, "followers": number|null,
                 "tier": "mid"|"micro"|null, "niche": str|null},
     "deliverables": [
       {"format": "reel"|"carousel"|"story", "deal_type": "paid"|"barter"|"affiliate"|"paid_plus_bonus",
        "fee": number|null, "barter_value": number|null, "bonus_threshold": number|null, "bonus_amount": number|null,
        "min_reach": number|null, "min_reach_explicitly_none": bool,
        "due_in_days": number|null,
        "required_tag": str|null, "required_hashtag": str|null, "requires_link_sticker": bool|null,
        "waived_notes": {"required_tag"?: str, "required_hashtag"?: str, "requires_link_sticker"?: str}}
     ]}
  ]
}

Null semantics — same rules as the single-creator deal note, applied per creator:
- null on a deliverable's required_tag/required_hashtag/requires_link_sticker means "not mentioned —
  inherit the campaign default." "" or false means "negotiated away," and MUST carry a matching
  waived_notes entry quoting the stated reason (or "Waived at intake — reason not stated" if none given).
- min_reach_explicitly_none=true ONLY when the note explicitly says no minimum was promised for that
  deliverable. Never assume absence means waived.

days_running: how many days the campaign has ALREADY been live, if the note says so (e.g. "running for
9 days", "day 6 of 14", "launched last week"). null if the note doesn't say — never guess from context.
This is the ONE thing that makes an in-flight campaign different from a brand-new one, so read it
carefully; it is NOT the same as duration_days (the campaign's total planned length).

Hard prohibitions (identical reasoning to the single-creator note, applied campaign-wide):
- NEVER output avg_reach, avg_engagement_rate, or any performance number for any creator — those are
  estimated by the server from follower count, never by you.
- NEVER output required_disclosure as empty or implied-waived at the campaign level — disclosure can
  never be waived. If the note doesn't state one, output null and let the server apply its own default.
- NEVER compute a calendar date. Only emit due_in_days (per deliverable) and days_running (for the
  campaign) as integer day counts; the server does all date arithmetic against today's date.
- One creator block per creator actually named — never invent a creator to round out a number mentioned
  in passing (e.g. "signing about 10 creators this week" names no one; emit an empty creators list).

Example — "New 14-day GlowLeaf relaunch, already running for 5 days. Signed @glowgirlpriya for 1 reel,
₹20k, min reach 15k, due in 3 days. Also @riya.unfiltered for 2 stories, barter worth ₹6k, no reach
guarantee, due day 8." ->
{"campaign": {"name": "GlowLeaf relaunch", "brand_name": "GlowLeaf", "product": null,
  "duration_days": 14, "days_running": 5, "required_disclosure": null, "required_tag": null,
  "required_hashtag": null, "requires_link_sticker": null, "banned_claims": null},
 "creators": [
   {"creator": {"handle": "glowgirlpriya", "raw_name": null, "followers": null, "tier": null, "niche": null},
    "deliverables": [{"format": "reel", "deal_type": "paid", "fee": 20000, "barter_value": null,
      "bonus_threshold": null, "bonus_amount": null, "min_reach": 15000, "min_reach_explicitly_none": false,
      "due_in_days": 3, "required_tag": null, "required_hashtag": null, "requires_link_sticker": null,
      "waived_notes": {}}]},
   {"creator": {"handle": "riya.unfiltered", "raw_name": null, "followers": null, "tier": null, "niche": null},
    "deliverables": [
      {"format": "story", "deal_type": "barter", "fee": null, "barter_value": 6000, "bonus_threshold": null,
       "bonus_amount": null, "min_reach": null, "min_reach_explicitly_none": true, "due_in_days": null,
       "required_tag": null, "required_hashtag": null, "requires_link_sticker": null, "waived_notes": {}},
      {"format": "story", "deal_type": "barter", "fee": null, "barter_value": 6000, "bonus_threshold": null,
       "bonus_amount": null, "min_reach": null, "min_reach_explicitly_none": true, "due_in_days": null,
       "required_tag": null, "required_hashtag": null, "requires_link_sticker": null, "waived_notes": {}}
    ]}
 ]}"""


def _extract_campaign_json(text: str | None) -> dict | None:
    """Mirrors _extract_json below, but validates the campaign-brief shape
    (a "campaign" dict plus a "creators" list) instead of a single creator's
    "deliverables" list."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("campaign"), dict) or not isinstance(parsed.get("creators"), list):
        return None
    return parsed


def parse_campaign_brief(ai_enabled: bool, brief_text: str, known_handles: list[str]) -> dict:
    """The campaign-scope analogue of parse_deal_brief, for entering a whole
    campaign (app/campaign_intake.py) rather than one creator deal into an
    existing one. Same non-negotiable rule: the caller never structurally
    trusts this result — campaign_intake.py's normalize_campaign_draft and
    validate_campaign_draft run on it regardless of which path produced it."""
    if ai_enabled:
        user_prompt = f"Known existing creator handles: {', '.join(known_handles)}.\n\nNote: {brief_text}"
        text = call_ai(_CAMPAIGN_BRIEF_SYSTEM_PROMPT, user_prompt, max_tokens=1800, temperature=0.1)
        parsed = _extract_campaign_json(text)
        if parsed is not None:
            return {**parsed, "source": "ai", "brief_text": brief_text}
    fallback = tpl.parse_campaign_brief_fallback(brief_text, known_handles)
    return {**fallback, "source": "template", "brief_text": brief_text}


def _extract_json(text: str | None) -> dict | None:
    """Defensive — this call has no response_format=json enforcement, so a
    malformed reply is a NORMAL outcome here, not an error path. Any failure
    falls through to the deterministic fallback exactly like a missing key."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("deliverables"), list):
        return None
    return parsed


def parse_deal_brief(ai_enabled: bool, brief_text: str, campaign: dict, current_day: int,
                      duration_days: int, known_handles: list[str]) -> dict:
    """The one AI task whose output could become an input the rules engine
    measures against (see app/intake.py's module docstring). The caller NEVER
    structurally trusts this result — app/intake.py:normalize_draft and
    validate_draft run on it regardless of which path produced it."""
    if ai_enabled:
        user_prompt = (
            f"Campaign defaults — tag: {campaign['required_tag']}, hashtag: {campaign['required_hashtag']}, "
            f"disclosure: {campaign['required_disclosure']}, link sticker required by default: "
            f"{bool(campaign['requires_link_sticker'])}. Today is campaign day {current_day} of {duration_days}. "
            f"Known existing creator handles: {', '.join(known_handles)}.\n\n"
            f"Note: {brief_text}"
        )
        text = call_ai(_BRIEF_SYSTEM_PROMPT, user_prompt, max_tokens=900, temperature=0.1)
        parsed = _extract_json(text)
        if parsed is not None:
            return {**parsed, "source": "ai", "brief_text": brief_text}
    fallback = tpl.parse_deal_brief_fallback(brief_text, campaign, current_day, duration_days, known_handles)
    return {**fallback, "source": "template", "brief_text": brief_text}
