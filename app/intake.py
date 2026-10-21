"""Deal intake: turns an account manager's free-text brief about a negotiated
creator deal into real `creators`/`deliverables`/`posts` rows.

This is the one AI task in the app whose output could become an input the
rules engine measures against — a wrong read of "no reach guarantee" would
otherwise silently change whether rule 5 ever fires. Two things keep that
safe:

1. AI (app/ai/provider.py:parse_deal_brief) and its deterministic fallback
   (app/ai/templates.py:parse_deal_brief_fallback) only ever produce a RAW
   draft. Nothing here trusts it structurally.
2. Everything in this module is DB-light and mostly pure — `validate_draft`
   takes no connection at all — so a hallucinated or garbled draft is caught
   by validation and shown to a human (app/main.py's /intake routes) before
   anything is written. commit_intake is the only function that writes.

This module never imports app/ai/* — it has to be fully testable and usable
with AI entirely absent, matching every other AI-adjacent feature in this app.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from app.rules.contract import resolve_terms

FORMATS = ("reel", "carousel", "story")
DEAL_TYPES = ("paid", "barter", "affiliate", "paid_plus_bonus")
TIERS = ("mid", "micro")

# Which deliverable override fields a brief is allowed to waive. required_disclosure
# is deliberately NOT here — see validate_draft's "disclosure can't be waived" check.
WAIVABLE = ("required_tag", "required_hashtag", "requires_link_sticker")

_HANDLE_RE = re.compile(r"^[a-z0-9._]{2,30}$")


class IntakeValidationError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


def campaign_row(conn: sqlite3.Connection, campaign_id: int) -> dict:
    row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise ValueError(f"no campaign with id {campaign_id}")
    return dict(row)


def known_handles(conn: sqlite3.Connection) -> list[str]:
    return [r["handle"] for r in conn.execute("SELECT handle FROM creators ORDER BY handle").fetchall()]


def attach_preview_notes(draft: dict, campaign: dict) -> dict:
    """Calls the SAME resolve_terms every detector reads, on the draft's own
    deliverable dicts, before anything is written — so the preview shows the
    exact contract-note text the queue would later show, produced by the one
    function that owns that explanation."""
    for d in draft["deliverables"]:
        d["preview_notes"] = resolve_terms(d, campaign).contract_notes
    return draft


def normalize_handle(raw: str) -> str:
    """Strip, drop a leading '@', lowercase, collapse whitespace. Lowercasing
    on write is load-bearing: creators.handle is UNIQUE but SQLite's UNIQUE
    has no COLLATE NOCASE, so 'Glow_With_Meera' would otherwise happily
    duplicate 'glow_with_meera'."""
    if not raw:
        return ""
    cleaned = raw.strip().lstrip("@").lower()
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def tier_for_followers(followers: int, thresholds: dict) -> str:
    floor = thresholds["intake"]["mid_tier_follower_floor"]
    return "mid" if followers >= floor else "micro"


def estimate_creator_metrics(followers: int, tier: str, thresholds: dict) -> tuple[float, float]:
    """Deterministic, config-driven estimate — never AI-invented (see
    app/ai/provider.py's parse_deal_brief prompt). avg_reach=0 is NOT a safe
    'unknown' sentinel: rule_5's avg_cutoff would become 0 (permanently
    unable to fire) and rule_12 explicitly early-returns on <= 0. An honest,
    labelled estimate is the only acceptable default."""
    intake_cfg = thresholds["intake"]
    reach_rate = intake_cfg["estimated_reach_rate"][tier]
    engagement_rate = intake_cfg["estimated_engagement_rate"][tier]
    return float(followers) * reach_rate, engagement_rate


def find_creator_by_handle(conn: sqlite3.Connection, handle: str) -> dict | None:
    row = conn.execute("SELECT * FROM creators WHERE lower(handle) = lower(?) LIMIT 1", (handle,)).fetchone()
    return dict(row) if row else None


def suggest_existing_creators(conn: sqlite3.Connection, handle: str, raw_name: str | None) -> list[dict]:
    """Non-authoritative fuzzy suggestions ONLY — never auto-applied. A
    first-name substring match ('priya' in 'glowgirlpriya') is offered as a
    radio choice in the preview, exactly because it is not reliable enough to
    act on without a human looking at it."""
    needle = (raw_name or handle or "").strip().lower()
    if len(needle) < 3:
        return []
    rows = conn.execute("SELECT id, handle FROM creators ORDER BY handle").fetchall()
    return [
        {"creator_id": r["id"], "handle": r["handle"], "why": f"'{needle}' appears in this handle"}
        for r in rows
        if needle in r["handle"].lower() and r["handle"].lower() != handle.lower()
    ]


def resolve_due_date(campaign_row: dict, due_day: int) -> str:
    """Absolute ISO datetime for an absolute campaign day, inheriting the
    campaign's own day-1 time-of-day (never wall-clock datetime.now()) —
    matches PostContext.due_day's own (promised_date - campaign_start).days + 1."""
    campaign_start = datetime.fromisoformat(campaign_row["start_date"])
    return (campaign_start + timedelta(days=due_day - 1)).isoformat()


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    f = _as_float(value)
    return None if f is None else int(f)


def normalize_draft(conn: sqlite3.Connection, raw: dict, campaign_row: dict, current_day: int,
                     thresholds: dict) -> dict:
    """Coerces EITHER the AI's or the fallback extractor's raw output into the
    one canonical draft shape every other function in this module and the
    preview template consume. An unknown enum degrades to a safe default plus
    a warning rather than raising — both input paths funnel through here."""
    warnings: list[dict] = []
    raw = raw if isinstance(raw, dict) else {}
    raw_creator = raw.get("creator") or {}
    raw_deliverables = raw.get("deliverables") or []

    handle = normalize_handle(raw_creator.get("handle") or "")
    existing = find_creator_by_handle(conn, handle) if handle else None
    existing_id = existing["id"] if existing else None
    suggestions = [] if existing else suggest_existing_creators(conn, handle, raw_creator.get("raw_name"))
    if not existing and raw_creator.get("handle_note"):
        warnings.append({"field": "creator.handle", "message": raw_creator["handle_note"]})

    if existing:
        followers = existing["followers"]
        tier = existing["tier"]
        niche = existing["niche"]
        avg_reach = existing["avg_reach"]
        avg_engagement_rate = existing["avg_engagement_rate"]
        metrics_source = existing.get("metrics_source") or "measured"
    else:
        followers = _as_int(raw_creator.get("followers")) or 0
        tier = raw_creator.get("tier") if raw_creator.get("tier") in TIERS else tier_for_followers(followers, thresholds)
        niche = (raw_creator.get("niche") or "").strip()
        est_reach, est_rate = estimate_creator_metrics(followers, tier, thresholds)
        # 0 is never a real average (it would silently disable rules 5/12), so 0/blank
        # means "not given" and the estimate is recomputed from the follower count.
        avg_reach = _as_float(raw_creator.get("avg_reach")) or None
        avg_engagement_rate = _as_float(raw_creator.get("avg_engagement_rate")) or None
        if avg_engagement_rate is not None and 1 < avg_engagement_rate <= 100:
            avg_engagement_rate /= 100
            warnings.append({
                "field": "creator.avg_engagement_rate",
                "message": f"Engagement rate read as a percentage — stored as {avg_engagement_rate:.4f}.",
            })
        # The AI prompt and the fallback never emit these two fields, so a value here
        # came from the AM's edit form: it's 'am_entered' only if it actually differs
        # from the (rounded) estimate the form was pre-filled with.
        reach_overridden = avg_reach is not None and abs(avg_reach - round(est_reach, 1)) > 0.5
        rate_overridden = avg_engagement_rate is not None and abs(avg_engagement_rate - round(est_rate, 4)) > 0.00005
        metrics_source = "am_entered" if reach_overridden or rate_overridden else "estimated"
        if avg_reach is None:
            avg_reach = est_reach
        if avg_engagement_rate is None:
            avg_engagement_rate = est_rate

    deliverables = []
    for i, d in enumerate(raw_deliverables):
        d = d if isinstance(d, dict) else {}
        fmt = d.get("format") if d.get("format") in FORMATS else None
        if fmt is None:
            warnings.append({"field": f"deliverables[{i}].format", "message": "Format not recognized — assumed 'reel'."})
            fmt = "reel"
        deal_type = d.get("deal_type") if d.get("deal_type") in DEAL_TYPES else "paid"

        due_day = d.get("due_day")
        if due_day is None and d.get("due_in_days") is not None:
            due_day = current_day + int(d["due_in_days"])
        due_day = _as_int(due_day)
        if due_day is None:
            warnings.append({"field": f"deliverables[{i}].due_day", "message": "No due date stated — assumed today's campaign day."})
            due_day = current_day

        waived_notes = d.get("waived_notes") if isinstance(d.get("waived_notes"), dict) else {}
        # required_disclosure can never be waived through intake (see validate_draft) —
        # strip it here too so a tampered/hallucinated '' never survives normalization.
        required_disclosure = d.get("required_disclosure")
        if required_disclosure == "":
            required_disclosure = None
            warnings.append({
                "field": f"deliverables[{i}].required_disclosure",
                "message": "This brief appears to waive the disclosure requirement — disclosure can't be waived through intake. Left as 'inherit campaign default'.",
            })

        min_reach = _as_int(d.get("min_reach"))
        min_reach_explicitly_none = bool(d.get("min_reach_explicitly_none")) and min_reach is None
        if min_reach is None and not min_reach_explicitly_none:
            warnings.append({
                "field": f"deliverables[{i}].min_reach",
                "message": "No minimum reach entered. Rule 5 (Underperforming) will never fire for this deliverable — confirm that's intentional.",
            })

        deliverables.append({
            "format": fmt, "deal_type": deal_type,
            "fee": _as_float(d.get("fee")),
            "barter_value": _as_float(d.get("barter_value")),
            "bonus_threshold": _as_int(d.get("bonus_threshold")),
            "bonus_amount": _as_float(d.get("bonus_amount")),
            "min_reach": min_reach,
            "min_reach_explicitly_none": min_reach_explicitly_none,
            "due_day": due_day,
            # None = inherit the campaign default; '' = explicitly waived. d.get()
            # preserves that distinction on its own (a missing key -> None; an
            # explicit '' -> '').
            "required_tag": d.get("required_tag"),
            "required_hashtag": d.get("required_hashtag"),
            "required_disclosure": required_disclosure,
            "requires_link_sticker": d.get("requires_link_sticker"),
            "waived_notes": {k: v for k, v in waived_notes.items() if k in WAIVABLE},
        })

    if not deliverables:
        warnings.append({"field": "deliverables", "message": "No deliverables recognized — add at least one before confirming."})

    return {
        "source": raw.get("source", "template"),
        "brief_text": raw.get("brief_text", ""),
        "creator": {
            "handle": handle, "existing_creator_id": existing_id, "existing_suggestions": suggestions,
            "followers": followers, "tier": tier, "niche": niche,
            "avg_reach": round(avg_reach, 1), "avg_engagement_rate": round(avg_engagement_rate, 4),
            "metrics_source": metrics_source,
        },
        "deliverables": deliverables,
        "warnings": warnings, "errors": [],
    }


def validate_draft(draft: dict, campaign_row: dict, thresholds: dict) -> list[dict]:
    """Pure — no DB. Called at preview AND again inside commit_intake, so a
    tampered or stale hidden field never bypasses these checks just because
    the preview once looked fine."""
    errors: list[dict] = []
    c = draft.get("creator", {})
    duration_days = campaign_row["duration_days"]

    if not c.get("existing_creator_id"):
        handle = c.get("handle", "")
        if not handle or not _HANDLE_RE.match(handle):
            errors.append({"field": "creator.handle", "message": "Handle must be 2-30 lowercase letters/digits/._", "blocking": True})
        followers = c.get("followers")
        if not isinstance(followers, (int, float)) or followers <= 0:
            errors.append({"field": "creator.followers", "message": "Followers must be a positive number.", "blocking": True})
        if c.get("tier") not in TIERS:
            errors.append({"field": "creator.tier", "message": "Tier must be 'mid' or 'micro'.", "blocking": True})
        if not (c.get("niche") or "").strip():
            errors.append({"field": "creator.niche", "message": "Niche is required.", "blocking": True})
        avg_reach = c.get("avg_reach")
        followers_ok = isinstance(followers, (int, float)) and followers > 0
        # With no follower count the estimate is necessarily 0 — the followers error already says why.
        if followers_ok and (not isinstance(avg_reach, (int, float)) or avg_reach <= 0):
            errors.append({"field": "creator.avg_reach", "message": "Average reach must be greater than 0 — 0 silently disables rules 5 and 12 for this creator.", "blocking": True})
        rate = c.get("avg_engagement_rate")
        if not isinstance(rate, (int, float)) or not (0 < rate < 1):
            errors.append({"field": "creator.avg_engagement_rate", "message": "Engagement rate must be a fraction between 0 and 1 (e.g. 0.05 for 5%).", "blocking": True})

    deliverables = draft.get("deliverables", [])
    max_deliverables = thresholds["intake"]["max_deliverables_per_brief"]
    if not (1 <= len(deliverables) <= max_deliverables):
        errors.append({"field": "deliverables", "message": f"A brief must produce 1-{max_deliverables} deliverables.", "blocking": True})

    for i, d in enumerate(deliverables):
        prefix = f"deliverables[{i}]"
        if d.get("format") not in FORMATS:
            errors.append({"field": f"{prefix}.format", "message": "Format must be reel, carousel, or story.", "blocking": True})
        deal_type = d.get("deal_type")
        if deal_type not in DEAL_TYPES:
            errors.append({"field": f"{prefix}.deal_type", "message": "Unknown deal type.", "blocking": True})

        for field_name in ("fee", "barter_value", "bonus_amount"):
            v = d.get(field_name)
            if v is not None and (not isinstance(v, (int, float)) or v < 0):
                errors.append({"field": f"{prefix}.{field_name}", "message": f"{field_name} must be a non-negative number or blank.", "blocking": True})
        for field_name in ("min_reach", "bonus_threshold"):
            v = d.get(field_name)
            if v is not None and (not isinstance(v, (int, float)) or v < 0):
                errors.append({"field": f"{prefix}.{field_name}", "message": f"{field_name} must be a non-negative number or blank.", "blocking": True})

        due_day = d.get("due_day")
        if not isinstance(due_day, int) or not (1 <= due_day <= duration_days):
            errors.append({"field": f"{prefix}.due_day", "message": f"Due day must be between 1 and {duration_days}.", "blocking": True})

        if deal_type in ("barter", "affiliate") and d.get("fee"):
            errors.append({"field": f"{prefix}.fee", "message": f"A {deal_type} deal can't also carry a cash fee.", "blocking": True})
        if deal_type == "paid" and not d.get("fee"):
            errors.append({"field": f"{prefix}.fee", "message": "A paid deal needs a fee.", "blocking": True})
        if deal_type == "paid_plus_bonus" and (d.get("bonus_threshold") is None or d.get("bonus_amount") is None):
            errors.append({"field": f"{prefix}.bonus", "message": "paid_plus_bonus needs both a bonus_threshold and a bonus_amount.", "blocking": True})
        if deal_type == "barter" and not d.get("barter_value"):
            errors.append({"field": f"{prefix}.barter_value", "message": "Barter value is unknown — the deal's rupee-equivalent won't show anywhere.", "blocking": False})

        if d.get("required_disclosure") == "":
            errors.append({"field": f"{prefix}.required_disclosure", "message": "Disclosure can never be waived through intake.", "blocking": True})

        waived_notes = d.get("waived_notes") or {}
        bad_keys = set(waived_notes) - set(WAIVABLE)
        if bad_keys:
            errors.append({"field": f"{prefix}.waived_notes", "message": f"Unknown waived field(s): {', '.join(sorted(bad_keys))}.", "blocking": True})
        try:
            json.dumps(waived_notes)
        except TypeError:
            errors.append({"field": f"{prefix}.waived_notes", "message": "Waived notes must be plain text.", "blocking": True})

    return errors


def _write_intake(conn: sqlite3.Connection, draft: dict, campaign_row: dict) -> dict:
    """The actual INSERTs for one creator + their deliverables, with no
    validation and no commit/rollback of its own — the caller owns both. Split
    out so app/campaign_intake.py:commit_campaign can write several creators
    into a brand-new campaign inside ONE outer transaction (its own commit/
    rollback spans the whole campaign, not just one creator) while
    commit_intake below keeps committing immediately for the single-creator
    deal-intake flow it has always served."""
    c = draft["creator"]
    if c.get("existing_creator_id"):
        creator_id = c["existing_creator_id"]
        created_creator = False
    else:
        conn.execute(
            "INSERT INTO creators (handle, followers, tier, niche, avg_reach, avg_engagement_rate, metrics_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(handle) DO NOTHING",
            (c["handle"], c["followers"], c["tier"], c["niche"], c["avg_reach"], c["avg_engagement_rate"], c["metrics_source"]),
        )
        row = conn.execute("SELECT id FROM creators WHERE handle = ?", (c["handle"],)).fetchone()
        creator_id = row["id"]
        created_creator = True  # best-effort; a true race lands as False-positive only in the return value, never in the data

    deliverable_ids: list[int] = []
    post_ids: list[int] = []
    for d in draft["deliverables"]:
        waived_notes = d.get("waived_notes") or {}
        cur = conn.execute(
            "INSERT INTO deliverables (campaign_id, creator_id, format, fee, promised_date, min_reach, "
            "required_disclosure, required_tag, required_hashtag, requires_link_sticker, "
            "deal_type, barter_value, bonus_threshold, bonus_amount, waived_notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign_row["id"], creator_id, d["format"], d.get("fee"), resolve_due_date(campaign_row, d["due_day"]),
             d.get("min_reach"), d.get("required_disclosure"), d.get("required_tag"), d.get("required_hashtag"),
             d.get("requires_link_sticker"), d["deal_type"], d.get("barter_value"), d.get("bonus_threshold"),
             d.get("bonus_amount"), json.dumps(waived_notes) if waived_notes else None),
        )
        did = cur.lastrowid
        deliverable_ids.append(did)

        pcur = conn.execute(
            "INSERT INTO posts (deliverable_id, posted_at, caption, original_caption, caption_edited_at, "
            "link_sticker_present, permalink, is_story, screenshot_uploaded, deleted_at_day, competitor_mentioned_day) "
            "VALUES (?, NULL, NULL, NULL, NULL, 0, NULL, ?, 0, NULL, NULL)",
            (did, int(d["format"] == "story")),
        )
        post_ids.append(pcur.lastrowid)

        conn.execute(
            "INSERT INTO decisions (flag_id, post_id, action, message_text, created_at, source) "
            "VALUES (NULL, ?, 'approve', ?, ?, 'intake')",
            (pcur.lastrowid, draft.get("brief_text", ""), datetime.now().isoformat()),
        )

    return {"creator_id": creator_id, "created_creator": created_creator,
            "deliverable_ids": deliverable_ids, "post_ids": post_ids}


def commit_intake(conn: sqlite3.Connection, draft: dict, campaign_row: dict, thresholds: dict) -> dict:
    """The single transactional writer for the single-creator deal-intake flow.
    campaign_id is read from campaign_row["id"] rather than taken as a separate
    argument — campaign_row always comes from this module's own campaign_row()
    lookup, so there is exactly one source of truth for which campaign a draft
    commits into; a caller can no longer pass a draft resolved against one
    campaign while writing into another by mistake.
    Re-validates inside the transaction (a handle can collide, or a tampered form can arrive, between preview and
    confirm) and rolls back cleanly on any failure — this codebase otherwise
    only ever commits, so this discipline is new and deliberate."""
    blocking = [e for e in validate_draft(draft, campaign_row, thresholds) if e["blocking"]]
    if blocking:
        raise IntakeValidationError(blocking)

    try:
        result = _write_intake(conn, draft, campaign_row)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
