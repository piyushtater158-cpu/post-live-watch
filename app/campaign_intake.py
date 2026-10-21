"""Campaign intake: turns an account manager's brief — typed into a form, or
pasted as free text and AI/keyword-drafted into one — into a real campaign
plus every signed creator's deal, in one transaction. Exists for exactly the
gap app/intake.py (one creator into an EXISTING campaign) can't cover: there
being no campaign at all yet, or an in-flight campaign nobody entered because
it predates this tool.

Mirrors app/intake.py's discipline on purpose, down to reusing its code:
1. AI (app/ai/provider.py:parse_campaign_brief) and its deterministic fallback
   (app/ai/templates.py:parse_campaign_brief_fallback) only ever produce a RAW
   draft. Nothing here trusts it structurally.
2. normalize_campaign_draft/validate_campaign_draft are DB-light/pure (the
   latter takes no connection at all) — a human always confirms before
   anything is written. commit_campaign is the only function that writes.
3. Each creator block in the draft IS an app/intake.py creator draft — built
   by calling intake.normalize_draft per creator against this campaign's own
   (not-yet-saved) terms, and validated by calling intake.validate_draft per
   creator. The WAIVABLE/FORMATS/DEAL_TYPES/TIERS rules, the handle-dedup
   logic, the follower-count estimate, the fuzzy existing-creator suggestions
   — none of that is reimplemented here.

commit_campaign inserts the brand and campaign rows, then writes every
creator through intake._write_intake (the same INSERTs commit_intake uses)
inside ONE outer transaction spanning the whole campaign — not one commit per
creator, which would leave a half-written campaign on a later creator's
failure.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from app import intake

MAX_NAME_LENGTH = 200
METRICS_PROVIDERS = ("seeded", "manual", "instagram")


class CampaignValidationError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def list_brands(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT id, name, product FROM brands ORDER BY name").fetchall()]


def attach_preview_notes(draft: dict) -> dict:
    """Calls intake.attach_preview_notes per creator against this DRAFT's own
    (not-yet-saved) campaign terms — the campaign-scope mirror of what
    app/intake.py's own attach_preview_notes does for one creator joining an
    existing campaign. Works unchanged because intake.resolve_terms/
    attach_preview_notes only ever read plain dict keys, never a real DB row."""
    for creator_draft in draft["creators"]:
        intake.attach_preview_notes(creator_draft, draft["campaign"])
    return draft


def normalize_campaign_draft(conn: sqlite3.Connection, raw: dict, today: datetime, thresholds: dict) -> dict:
    """Coerces the AI's, the fallback's, or the typed form's raw output into the
    one canonical campaign-draft shape every other function here and the
    preview template consume. Each creators[i] IS the exact dict
    intake.normalize_draft already returns for that creator — same per-creator
    warnings, suggestions, and metrics-estimate honesty intake.py already has."""
    cfg = thresholds["campaign_intake"]
    warnings: list[dict] = []
    raw = raw if isinstance(raw, dict) else {}
    raw_campaign = raw.get("campaign") or {}
    raw_creators = raw.get("creators") or []

    name = (raw_campaign.get("name") or "").strip()[:MAX_NAME_LENGTH]

    existing_brand_id = _as_int(raw_campaign.get("existing_brand_id"))
    brand_name = (raw_campaign.get("brand_name") or "").strip()
    if existing_brand_id:
        brand = conn.execute("SELECT id, name FROM brands WHERE id = ?", (existing_brand_id,)).fetchone()
        if brand is None:
            warnings.append({"field": "campaign.existing_brand_id",
                              "message": "That brand no longer exists — treating this as a new brand."})
            existing_brand_id = None
        else:
            brand_name = brand["name"]

    duration_days = _as_int(raw_campaign.get("duration_days")) or cfg["default_duration_days"]
    days_running = _as_int(raw_campaign.get("days_running"))
    if days_running is not None and days_running < 1:
        warnings.append({"field": "campaign.days_running", "message": "Days running must be positive — ignored."})
        days_running = None

    # A brand-new campaign starts today (day 1). An in-flight one back-computes
    # its start date from how many days it's already been running, so the live
    # clock (app/db.py:get_campaign_day) immediately reports the right day
    # instead of restarting the count from day 1.
    anchor = today.replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = anchor - timedelta(days=(days_running - 1)) if days_running else anchor

    required_disclosure = (raw_campaign.get("required_disclosure") or cfg["default_required_disclosure"]).strip()
    required_tag = (raw_campaign.get("required_tag") or "").strip()
    required_hashtag = (raw_campaign.get("required_hashtag") or "").strip()
    requires_link_sticker = raw_campaign.get("requires_link_sticker")
    requires_link_sticker = True if requires_link_sticker is None else bool(requires_link_sticker)
    banned_claims_raw = raw_campaign.get("banned_claims")
    banned_claims = [str(c) for c in banned_claims_raw] if isinstance(banned_claims_raw, list) else []

    campaign = {
        "name": name,
        "existing_brand_id": existing_brand_id,
        "brand_name": brand_name,
        "product": (raw_campaign.get("product") or "").strip(),
        "duration_days": duration_days,
        "days_running": days_running,
        "start_date": start_date.isoformat(),
        "required_disclosure": required_disclosure,
        "required_tag": required_tag,
        "required_hashtag": required_hashtag,
        "requires_link_sticker": requires_link_sticker,
        "banned_claims": banned_claims,
    }

    # The provisional terms intake.normalize_draft/validate_draft read — not a
    # DB row (this campaign has no id yet), just the fields those pure
    # functions actually use (see app/intake.py's own campaign_row() callers).
    provisional_campaign_row = {
        "duration_days": duration_days,
        "required_disclosure": required_disclosure,
        "required_tag": required_tag,
        "required_hashtag": required_hashtag,
        "requires_link_sticker": requires_link_sticker,
    }
    # due_in_days offsets (e.g. "due in 3 days" in a pasted brief) are relative
    # to the campaign's OWN current day at the moment of intake — day 1 for a
    # brand-new campaign, days_running for one already in flight — never to
    # some other campaign's day or today's wall-clock date.
    effective_current_day = days_running or 1

    max_creators = cfg["max_creators_per_brief"]
    if len(raw_creators) > max_creators:
        warnings.append({"field": "creators",
                          "message": f"More than {max_creators} creators named — only the first {max_creators} were kept."})
        raw_creators = raw_creators[:max_creators]

    creators = []
    for rc in raw_creators:
        rc = rc if isinstance(rc, dict) else {}
        sub_raw = {
            "source": raw.get("source", "form"),
            "brief_text": raw.get("brief_text", ""),  # the whole campaign brief, same as every
                                                        # creator's audit row under app/intake.py's
                                                        # single-creator flow stores its own brief
            "creator": rc.get("creator") if isinstance(rc.get("creator"), dict) else rc,
            "deliverables": rc.get("deliverables") or [],
        }
        creators.append(intake.normalize_draft(conn, sub_raw, provisional_campaign_row, effective_current_day, thresholds))

    if not creators:
        warnings.append({"field": "creators", "message": "No creators recognized — add at least one before confirming."})

    return {
        "source": raw.get("source", "form"),
        "brief_text": raw.get("brief_text", ""),
        "campaign": campaign,
        "creators": creators,
        "warnings": warnings,
        "errors": [],
    }


def validate_campaign_draft(draft: dict, thresholds: dict) -> list[dict]:
    """Pure — no DB, matching app/intake.py:validate_draft. Called at preview
    AND again inside commit_campaign, for the same reason intake.py's does:
    a tampered or stale hidden field must never bypass these checks just
    because the preview once looked fine."""
    cfg = thresholds["campaign_intake"]
    errors: list[dict] = []
    c = draft.get("campaign", {})

    if not (c.get("name") or "").strip():
        errors.append({"field": "campaign.name", "message": "Campaign name is required.", "blocking": True})
    if not c.get("existing_brand_id") and not (c.get("brand_name") or "").strip():
        errors.append({"field": "campaign.brand_name",
                        "message": "Brand name is required, or pick an existing brand.", "blocking": True})

    duration_days = c.get("duration_days")
    if not isinstance(duration_days, int) or not (1 <= duration_days <= cfg["max_duration_days"]):
        errors.append({"field": "campaign.duration_days",
                        "message": f"Duration must be between 1 and {cfg['max_duration_days']} days.", "blocking": True})

    days_running = c.get("days_running")
    if days_running is not None:
        if not isinstance(days_running, int) or days_running < 1:
            errors.append({"field": "campaign.days_running", "message": "Days running must be a positive number.", "blocking": True})
        elif isinstance(duration_days, int) and days_running > duration_days:
            errors.append({"field": "campaign.days_running",
                            "message": "Days running can't exceed the campaign's total duration.", "blocking": True})

    # Mirrors intake.py's own rule: disclosure can never be waived, so it can
    # never be blank at the campaign level either — every deliverable inherits
    # this unless it names its own (still non-empty) override.
    if not (c.get("required_disclosure") or "").strip():
        errors.append({"field": "campaign.required_disclosure",
                        "message": "A disclosure requirement is required — it can never be waived.", "blocking": True})

    try:
        json.dumps(c.get("banned_claims") or [])
    except TypeError:
        errors.append({"field": "campaign.banned_claims", "message": "Banned claims must be plain text.", "blocking": True})

    creators = draft.get("creators", [])
    if not creators:
        errors.append({"field": "creators", "message": "At least one creator is required.", "blocking": True})
    elif len(creators) > cfg["max_creators_per_brief"]:
        errors.append({"field": "creators",
                        "message": f"A campaign brief must have at most {cfg['max_creators_per_brief']} creators.",
                        "blocking": True})

    provisional_campaign_row = {"duration_days": duration_days if isinstance(duration_days, int) else cfg["default_duration_days"]}
    for i, creator_draft in enumerate(creators):
        for e in intake.validate_draft(creator_draft, provisional_campaign_row, thresholds):
            errors.append({**e, "field": f"creators[{i}].{e['field']}"})

    return errors


_EDITABLE_FIELDS = (
    "name", "required_disclosure", "required_tag", "required_hashtag",
    "requires_link_sticker", "duration_days", "banned_claims",
)


def validate_campaign_edit(fields: dict, thresholds: dict) -> list[dict]:
    """Pure — the same bar as validate_campaign_draft, scaled down to the
    columns update_campaign_fields actually touches. An existing campaign's
    brand and start_date are not editable here: changing the brand is really
    'make a new campaign', and the day clock has its own dedicated action
    (app/actions.py:set_clock_mode) rather than a free-typed date field."""
    cfg = thresholds["campaign_intake"]
    errors: list[dict] = []
    if not (fields.get("name") or "").strip():
        errors.append({"field": "name", "message": "Campaign name is required.", "blocking": True})
    if not (fields.get("required_disclosure") or "").strip():
        errors.append({"field": "required_disclosure",
                        "message": "A disclosure requirement is required — it can never be waived.", "blocking": True})
    duration_days = fields.get("duration_days")
    if not isinstance(duration_days, int) or not (1 <= duration_days <= cfg["max_duration_days"]):
        errors.append({"field": "duration_days",
                        "message": f"Duration must be between 1 and {cfg['max_duration_days']} days.", "blocking": True})
    try:
        json.dumps(fields.get("banned_claims") or [])
    except TypeError:
        errors.append({"field": "banned_claims", "message": "Banned claims must be plain text.", "blocking": True})
    provider = fields.get("metrics_provider")
    if provider is not None and provider not in METRICS_PROVIDERS:
        errors.append({"field": "metrics_provider",
                        "message": f"Metrics source must be one of: {', '.join(METRICS_PROVIDERS)}.", "blocking": True})
    return errors


def update_campaign_fields(conn: sqlite3.Connection, campaign_id: int, fields: dict, thresholds: dict) -> dict:
    """The 'set format to update a campaign' the UI exposes on an EXISTING
    campaign — a structured field-by-field edit, not a re-run of intake's
    parse/draft/confirm pipeline (that's for creating something new; this is
    for correcting what's already there, e.g. a typo in the hashtag or a
    campaign that turned out to run longer than planned)."""
    blocking = [e for e in validate_campaign_edit(fields, thresholds) if e["blocking"]]
    if blocking:
        raise CampaignValidationError(blocking)

    conn.execute(
        "UPDATE campaigns SET name = ?, required_disclosure = ?, required_tag = ?, required_hashtag = ?, "
        "requires_link_sticker = ?, duration_days = ?, banned_claims = ? WHERE id = ?",
        (fields["name"], fields["required_disclosure"], fields.get("required_tag") or "",
         fields.get("required_hashtag") or "", int(bool(fields.get("requires_link_sticker"))),
         fields["duration_days"], json.dumps(fields.get("banned_claims") or []), campaign_id),
    )
    if fields.get("metrics_provider"):
        conn.execute("UPDATE campaigns SET metrics_provider = ? WHERE id = ?", (fields["metrics_provider"], campaign_id))
    conn.commit()
    return intake.campaign_row(conn, campaign_id)


def commit_campaign(conn: sqlite3.Connection, draft: dict, thresholds: dict) -> dict:
    """The single transactional writer. Inserts the brand (if new) and the
    campaign row, then writes every creator through intake._write_intake
    inside this SAME transaction — a failure on creator 5 of 12 rolls back
    the brand and campaign rows too, never leaving a half-signed campaign
    behind. day_override is always NULL (live clock, app/db.py:
    get_campaign_day): an intaken campaign's day tracks wall-clock time from
    its (possibly back-computed) start_date; switching it to a simulated
    clock is the separate, explicit app/actions.py:set_clock_mode action."""
    blocking = [e for e in validate_campaign_draft(draft, thresholds) if e["blocking"]]
    if blocking:
        raise CampaignValidationError(blocking)

    try:
        c = draft["campaign"]
        if c.get("existing_brand_id"):
            brand_id = c["existing_brand_id"]
        else:
            cur = conn.execute(
                "INSERT INTO brands (name, product) VALUES (?, ?)",
                (c["brand_name"], c.get("product") or ""),
            )
            brand_id = cur.lastrowid

        camp_cur = conn.execute(
            "INSERT INTO campaigns (brand_id, name, start_date, duration_days, required_disclosure, "
            "required_tag, required_hashtag, requires_link_sticker, banned_claims, day_override, "
            "status, metrics_provider, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', 'manual', ?)",
            (brand_id, c["name"], c["start_date"], c["duration_days"], c["required_disclosure"],
             c["required_tag"], c["required_hashtag"], int(c["requires_link_sticker"]),
             json.dumps(c["banned_claims"]), datetime.now().isoformat()),
        )
        campaign_id = camp_cur.lastrowid
        new_campaign_row = intake.campaign_row(conn, campaign_id)

        creator_results = [intake._write_intake(conn, cd, new_campaign_row) for cd in draft["creators"]]

        conn.commit()
        return {"campaign_id": campaign_id, "brand_id": brand_id, "creators": creator_results}
    except Exception:
        conn.rollback()
        raise
