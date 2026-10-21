"""Template/keyword fallback text — used when AI is off, no API key is set,
or the OpenRouter call fails. The app must work end-to-end on these alone.
"""

from __future__ import annotations

import re


def underperform_explanation(creator_handle: str, reach: int, min_reach: int, avg_reach: float,
                              avg_reach_source: str | None = None) -> str:
    gap_vs_promise = round((1 - reach / min_reach) * 100) if min_reach else 0
    avg_label = "estimated average" if avg_reach_source == "estimated" else "own average"
    return (
        f"@{creator_handle}'s post reached {reach} ({gap_vs_promise}% below the promised {min_reach}) "
        f"and under their {avg_label} of {avg_reach:.0f}. Likely cause: posting time, format mismatch, "
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


def nudge_message(creator_handle: str, rule_name: str, reason: str, brand_name: str = "the brand") -> str:
    return (
        f"Hi {creator_handle}! Quick note on the {brand_name} post — we noticed: {reason} "
        f"Could you take a look and fix this when you get a chance? Thanks so much! 🙏"
    )


def brand_alert_message(creator_handle: str, rule_name: str, reason: str) -> str:
    return f"Heads up — {creator_handle}'s post has an issue flagged as '{rule_name}': {reason}"


def brand_daily_report(day: int, duration: int, live_count: int, due_count: int,
                        total_reach: int, promised_reach: int, act_now: int, needs_look: int, ok: int,
                        campaign_name: str = "This campaign") -> str:
    return (
        f"Day {day} of {duration} — {campaign_name}\n\n"
        f"Posts live: {live_count}/{due_count}. Total reach so far: {total_reach:,} "
        f"(promised: {promised_reach:,}).\n"
        f"Status: {act_now} need action now, {needs_look} need a look, {ok} are on track.\n"
        f"This is a template summary (AI is off) — turn AI on for a narrative version."
    )


# ---------------------------------------------------------------------------
# Deal intake fallback (app/intake.py). Regex-based, deliberately worse than
# the AI path — matches how sentiment_summary above labels itself "keyword-
# match mode." Produces the same raw {"creator": {...}, "deliverables": [...]}
# shape app/ai/provider.py:parse_deal_brief's AI path produces, so both go
# through app/intake.py:normalize_draft identically. Anything this can't
# confidently extract is left None/empty rather than guessed — normalize_draft
# turns an unresolved field into a visible warning, never a silent default
# that looks like a real answer.
# ---------------------------------------------------------------------------

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_MONEY_MULTIPLIERS = {"k": 1e3, "lakh": 1e5, "lac": 1e5, "l": 1e5, "cr": 1e7}
_FORMAT_WORDS = {
    "reel": "reel", "reels": "reel",
    "carousel": "carousel", "carousels": "carousel",
    "story": "story", "stories": "story",
}
_KNOWN_NICHES = ("skincare", "beauty", "lifestyle", "fitness", "mom-and-baby")

_HANDLE_RE = re.compile(r"@([A-Za-z0-9._]{2,30})")
# The verb alternation needs to match "Signed"/"signed" alike while the name
# group stays case-SENSITIVE (requires a capital letter) — a bare re.IGNORECASE
# on the whole pattern would let [A-Z] match lowercase too and defeat that, so
# the (?i:...) scoped flag applies case-insensitivity to the verb group only.
_SIGNED_NAME_RE = re.compile(
    r"\b(?i:signed|booked|onboarded|added|renew(?:ing|ed)?|confirmed)\s+(?:with\s+)?([A-Z][a-zA-Z]+)\b"
)
_COUNT_FORMAT_RE = re.compile(
    r"(\d+|one|two|three|four|five|six)\s*(reels?|carousels?|stories|story|posts?)", re.IGNORECASE
)
_MONEY_RE = re.compile(r"(?:(₹|rs\.?|inr)\s?)?([\d,]+(?:\.\d+)?)\s*(k|lakh|lac|l|cr)\b", re.IGNORECASE)
_MONEY_WITH_SYMBOL_RE = re.compile(r"(₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)\b", re.IGNORECASE)
_MIN_REACH_WAIVED_RE = re.compile(
    r"no\s+reach\s+guarantee|no\s+(?:minimum|min)(?:\s+reach)?|without\s+(?:a\s+)?(?:reach\s+)?guarantee|no\s+guarantee",
    re.IGNORECASE,
)
# Two orderings in the wild: "reach guarantee of 40,000" (keyword first) and
# "40k min reach" (number first) — tried in that order by _find_min_reach.
_MIN_REACH_KEYWORD_FIRST_RE = re.compile(
    r"(?:min(?:imum)?\s*reach|reach(?:\s*(?:of|guarantee(?:d)?(?:\s*of)?))?|guarantee(?:ing)?)\D{0,12}"
    r"([\d,]+)\s*(k|lakh)?", re.IGNORECASE,
)
_MIN_REACH_NUMBER_FIRST_RE = re.compile(
    r"([\d,]+)\s*(k|lakh)?\s*(?:min(?:imum)?\s*reach|reach\s*guarantee(?:d)?)", re.IGNORECASE,
)
_FOLLOWERS_RE = re.compile(r"([\d.,]+)\s*(k|lakh|lac|m|million)?\s*followers", re.IGNORECASE)
_REASON_RE = re.compile(r"(?:due to|because|owing to|as (?:she|he|they) (?:has|have))\s+(.+?)(?:[.,]|$)", re.IGNORECASE)

# "(?:(?:our|the|campaign)\s+)*" repeats zero or more times so phrasing with
# several qualifiers ("skipping our campaign hashtag") still matches — a
# single optional word isn't enough.
_HASHTAG_WAIVE_RE = re.compile(
    r"(?:skip(?:ping)?|waiv\w*|drop(?:ping)?|not using|without|no)\s+(?:(?:our|the|campaign)\s+)*hashtag", re.IGNORECASE
)
_TAG_WAIVE_RE = re.compile(
    r"(?:skip(?:ping)?|waiv\w*|drop(?:ping)?|not using|without|no)\s+(?:(?:our|the|brand)\s+)*(?:tag|tagging)", re.IGNORECASE
)
_LINK_NO_RE = re.compile(r"no\s+link\s+sticker|without\s+(?:a\s+)?link\s+sticker", re.IGNORECASE)
_LINK_YES_RE = re.compile(r"link\s+sticker\s*(?:is\s*)?required|with\s+(?:a\s+)?link\s+sticker", re.IGNORECASE)

_DUE_BY_DAY_RE = re.compile(r"\bby\s+day\s+(\d+)\b", re.IGNORECASE)
_DUE_IN_DAYS_RE = re.compile(r"due\s+in\s+(\d+|one|two|three)\s+days?|\bin\s+(\d+)\s+days?\b", re.IGNORECASE)
_DUE_RELATIVE_RE = re.compile(r"\b(today|tomorrow|day after tomorrow)\b", re.IGNORECASE)
_DUE_NEXT_WEEK_RE = re.compile(r"\bnext week\b", re.IGNORECASE)


def _money_value(num: str, suffix: str | None) -> float:
    value = float(num.replace(",", ""))
    return value * _MONEY_MULTIPLIERS.get((suffix or "").lower(), 1)


def _find_money(text: str) -> list[dict]:
    """Every amount that carries EITHER a rupee symbol OR a k/lakh/cr suffix —
    a bare number with neither is too ambiguous (is '5' a day count, a reach
    figure, a fee?) and is deliberately left for the reach/date regexes to
    claim instead, or left unclaimed entirely."""
    found = []
    for m in _MONEY_RE.finditer(text):
        _, num, suffix = m.groups()
        found.append({"amount": _money_value(num, suffix), "context": text[max(0, m.start() - 40):m.start()].lower(), "start": m.start()})
    for m in _MONEY_WITH_SYMBOL_RE.finditer(text):
        if any(abs(m.start() - f["start"]) < 3 for f in found):
            continue  # already captured by the suffix regex above
        _, num = m.groups()
        found.append({"amount": _money_value(num, None), "context": text[max(0, m.start() - 40):m.start()].lower(), "start": m.start()})
    found.sort(key=lambda f: f["start"])
    return found


def _find_min_reach(text: str) -> tuple[int | None, re.Match | None]:
    m = _MIN_REACH_KEYWORD_FIRST_RE.search(text)
    if not m:
        m = _MIN_REACH_NUMBER_FIRST_RE.search(text)
    if not m:
        return None, None
    return int(_money_value(m.group(1), m.group(2))), m


def _extract_reason(text: str, after_pos: int) -> str:
    window = text[after_pos:after_pos + 100]
    m = _REASON_RE.search(window)
    if m:
        return m.group(1).strip().rstrip(".") + "."
    return "Waived at intake — reason not stated in the brief."


def parse_deal_brief_fallback(brief_text: str, campaign: dict, current_day: int,
                               duration_days: int, known_handles: list[str]) -> dict:
    text = brief_text or ""
    lower = text.lower()

    # --- creator handle ---------------------------------------------------
    handle_m = _HANDLE_RE.search(text)
    handle, raw_name, handle_note = None, None, None
    if handle_m:
        handle = handle_m.group(1)
    else:
        name_m = _SIGNED_NAME_RE.search(text)
        if name_m:
            raw_name = name_m.group(1)
            handle = re.sub(r"[^a-z0-9._]", "", raw_name.lower())
            handle_note = f"Handle guessed from the name '{raw_name}' — verify it's correct before confirming."

    followers = None
    fm = _FOLLOWERS_RE.search(text)
    if fm:
        followers = int(_money_value(fm.group(1), fm.group(2)))

    niche = next((n for n in _KNOWN_NICHES if n in lower), None)

    # --- deal type (brief-wide; applied to every deliverable) -------------
    if re.search(r"\bbarter\b|in exchange for (?:the )?product|product[- ]only|no cash", lower):
        deal_type = "barter"
    elif re.search(r"\baffiliate\b|commission|promo ?code|coupon", lower):
        deal_type = "affiliate"
    elif re.search(r"\bbonus\b", lower):
        deal_type = "paid_plus_bonus"
    else:
        deal_type = "paid"

    money = _find_money(text)
    fee = barter_value = bonus_amount = None
    for item in money:
        ctx = item["context"]
        if "bonus" in ctx and bonus_amount is None:
            bonus_amount = item["amount"]
        elif (deal_type == "barter" or "worth" in ctx or "value" in ctx) and barter_value is None:
            barter_value = item["amount"]
        elif deal_type not in ("affiliate", "barter") and fee is None:
            fee = item["amount"]

    # --- reach guarantee ----------------------------------------------------
    min_reach, min_reach_explicitly_none = None, False
    if _MIN_REACH_WAIVED_RE.search(lower):
        min_reach_explicitly_none = True
    else:
        min_reach, _ = _find_min_reach(text)

    bonus_threshold = None
    if deal_type == "paid_plus_bonus":
        bm = re.search(r"(?:above|over|crosses?|if it (?:hits|crosses))\D{0,12}([\d,]+)\s*(k|lakh)?", lower)
        if bm:
            bonus_threshold = int(_money_value(bm.group(1), bm.group(2)))

    # --- waivers -------------------------------------------------------------
    required_tag = required_hashtag = requires_link_sticker = None
    waived_notes: dict[str, str] = {}
    hm = _HASHTAG_WAIVE_RE.search(text)
    if hm:
        required_hashtag = ""
        waived_notes["required_hashtag"] = _extract_reason(text, hm.end())
    tm = _TAG_WAIVE_RE.search(text)
    if tm:
        required_tag = ""
        waived_notes["required_tag"] = _extract_reason(text, tm.end())
    if _LINK_NO_RE.search(lower):
        requires_link_sticker = False
    elif _LINK_YES_RE.search(lower):
        requires_link_sticker = True

    # --- due date (applied to every deliverable; the AI path can vary this
    # per-block, the regex path can't) ---------------------------------------
    due_day, due_in_days = None, None
    by_day_m = _DUE_BY_DAY_RE.search(lower)
    if by_day_m:
        due_day = int(by_day_m.group(1))
    else:
        rel_m = _DUE_RELATIVE_RE.search(lower)
        week_m = _DUE_NEXT_WEEK_RE.search(lower)
        in_days_m = _DUE_IN_DAYS_RE.search(lower)
        if rel_m:
            due_in_days = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}[rel_m.group(1)]
        elif week_m:
            due_in_days = 7
        elif in_days_m:
            raw = in_days_m.group(1) or in_days_m.group(2)
            due_in_days = _WORD_NUMBERS.get(raw.lower(), None) if raw and not raw.isdigit() else int(raw)

    # --- format/count blocks -------------------------------------------------
    deliverables = []
    for count_m in _COUNT_FORMAT_RE.finditer(text):
        raw_count, raw_fmt = count_m.groups()
        count = _WORD_NUMBERS.get(raw_count.lower(), None)
        if count is None and raw_count.isdigit():
            count = int(raw_count)
        count = count or 1
        fmt = _FORMAT_WORDS.get(raw_fmt.lower())  # None for 'post'/'posts' — ambiguous, left for normalize_draft
        for _ in range(count):
            deliverables.append({
                "format": fmt, "deal_type": deal_type,
                "fee": fee, "barter_value": barter_value,
                "bonus_threshold": bonus_threshold, "bonus_amount": bonus_amount,
                "min_reach": min_reach, "min_reach_explicitly_none": min_reach_explicitly_none,
                "due_day": due_day, "due_in_days": due_in_days,
                "required_tag": required_tag, "required_hashtag": required_hashtag,
                "requires_link_sticker": requires_link_sticker, "waived_notes": dict(waived_notes),
            })
    if not deliverables:
        deliverables.append({
            "format": None, "deal_type": deal_type,
            "fee": fee, "barter_value": barter_value,
            "bonus_threshold": bonus_threshold, "bonus_amount": bonus_amount,
            "min_reach": min_reach, "min_reach_explicitly_none": min_reach_explicitly_none,
            "due_day": due_day, "due_in_days": due_in_days,
            "required_tag": required_tag, "required_hashtag": required_hashtag,
            "requires_link_sticker": requires_link_sticker, "waived_notes": dict(waived_notes),
        })

    creator = {"handle": handle, "raw_name": raw_name, "followers": followers, "tier": None, "niche": niche}
    if handle_note:
        creator["handle_note"] = handle_note
    return {"creator": creator, "deliverables": deliverables}


# ---------------------------------------------------------------------------
# Campaign intake fallback (app/campaign_intake.py). Deliberately does NOT
# reimplement deal-term extraction: it splits the brief into one chunk per
# creator (at each @handle boundary) and runs parse_deal_brief_fallback
# above, UNCHANGED, on each chunk — the single-creator fallback's hard-won
# regex work (handle guessing, deal type, reach, waivers, due dates) belongs
# in exactly one place. Only the campaign-level fields below are new.
#
# With zero or one @handle in the whole brief, this can only split out a
# single creator — a brief naming several creators by name alone ("signed
# Priya and Riya for...") drafts just the first and leaves the rest for a
# human to add, same as any other fallback gap: validation catches it, the
# preview shows it, nothing is silently wrong.
# ---------------------------------------------------------------------------

_CAMPAIGN_NAME_RE = re.compile(r"(?:campaign(?:\s*name)?|brief)\s*[:\-]\s*([^\n,.;]{3,80})", re.IGNORECASE)
_BRAND_LABEL_RE = re.compile(r"(?:brand|client)\s*[:\-]\s*([^\n,.;]{2,60})", re.IGNORECASE)
_FOR_BRAND_RE = re.compile(r"\bfor\s+([A-Z][A-Za-z0-9&'.]*(?:\s+[A-Z][A-Za-z0-9&'.]*){0,3})(?:'s)?\s+(?:campaign|launch)\b")
_DURATION_DAYS_RE = re.compile(
    r"(\d{1,3})[- ]day\s+campaign"
    r"|campaign\s+(?:runs?|running)\s+(?:for\s+)?(\d{1,3})\s+days?"
    r"|duration\s*[:\-]?\s*(\d{1,3})\s+days?",
    re.IGNORECASE,
)
_DAYS_RUNNING_RE = re.compile(
    r"(?:already\s+)?(?:been\s+)?(?:running|live)\s+(?:for\s+)?(\d{1,3})\s+days?"
    r"|day\s+(\d{1,3})\s+of\s+\d{1,3}"
    r"|(\d{1,3})\s+days?\s+in\b",
    re.IGNORECASE,
)


def _first_group(match: re.Match | None) -> int | None:
    if not match:
        return None
    return next((int(g) for g in match.groups() if g), None)


def _campaign_fields_fallback(text: str) -> tuple[str | None, str | None, int | None, int | None]:
    name_m = _CAMPAIGN_NAME_RE.search(text)
    name = name_m.group(1).strip() if name_m else None

    brand_m = _BRAND_LABEL_RE.search(text) or _FOR_BRAND_RE.search(text)
    brand_name = brand_m.group(1).strip() if brand_m else None

    return name, brand_name, _first_group(_DURATION_DAYS_RE.search(text)), _first_group(_DAYS_RUNNING_RE.search(text))


def _split_creator_chunks(text: str) -> list[str]:
    handles = list(_HANDLE_RE.finditer(text))
    if len(handles) <= 1:
        return [text]
    return [
        text[m.start(): handles[i + 1].start() if i + 1 < len(handles) else len(text)]
        for i, m in enumerate(handles)
    ]


def parse_campaign_brief_fallback(brief_text: str, known_handles: list[str]) -> dict:
    text = brief_text or ""
    name, brand_name, duration_days, days_running = _campaign_fields_fallback(text)

    creators = []
    for chunk in _split_creator_chunks(text):
        # campaign/current_day/duration_days are accepted but unused by
        # parse_deal_brief_fallback itself (see its own definition above) —
        # passed as placeholders only to match its signature.
        creators.append(parse_deal_brief_fallback(chunk, {}, 0, 0, known_handles))

    return {
        "campaign": {
            "name": name, "brand_name": brand_name,
            "duration_days": duration_days, "days_running": days_running,
        },
        "creators": creators,
    }
