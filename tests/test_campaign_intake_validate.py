"""app/campaign_intake.py:normalize_campaign_draft/validate_campaign_draft —
pure functions, no writes. Mirrors tests/test_intake_normalize.py and
tests/test_intake_validate.py's coverage at campaign scope: campaign-level
field defaults/derivation, disclosure-never-waivable, duration bounds, and
that each creator block is validated through the EXACT SAME
intake.validate_draft every single-creator deal already goes through."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.campaign_intake import normalize_campaign_draft, validate_campaign_draft
from app.config import load_thresholds

THRESHOLDS = load_thresholds()
TODAY = datetime(2026, 10, 21, 9, 0, 0)


def _raw(**campaign_overrides):
    return {
        "source": "form", "brief_text": "x",
        "campaign": {"name": "Test Launch", "brand_name": "TestBrand", **campaign_overrides},
        "creators": [{
            "creator": {"handle": "freshcreator", "followers": 50000, "tier": "micro", "niche": "skincare"},
            "deliverables": [{"format": "reel", "deal_type": "paid", "fee": 10000, "min_reach": 8000, "due_day": 3}],
        }],
    }


def test_brand_new_campaign_starts_today(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    assert draft["campaign"]["start_date"] == TODAY.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    assert draft["campaign"]["days_running"] is None


def test_in_flight_campaign_backcomputes_start_date(conn):
    draft = normalize_campaign_draft(conn, _raw(days_running=9), TODAY, THRESHOLDS)
    expected_start = TODAY.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=8)
    assert draft["campaign"]["start_date"] == expected_start.isoformat()
    assert draft["campaign"]["days_running"] == 9


def test_missing_duration_days_falls_back_to_config_default(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    assert draft["campaign"]["duration_days"] == THRESHOLDS["campaign_intake"]["default_duration_days"]


def test_missing_disclosure_falls_back_to_config_default(conn):
    draft = normalize_campaign_draft(conn, _raw(required_disclosure=None), TODAY, THRESHOLDS)
    assert draft["campaign"]["required_disclosure"] == THRESHOLDS["campaign_intake"]["default_required_disclosure"]


def test_requires_link_sticker_defaults_true(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    assert draft["campaign"]["requires_link_sticker"] is True


def test_existing_brand_id_resolves_name(conn):
    brand = conn.execute("SELECT id, name FROM brands LIMIT 1").fetchone()
    draft = normalize_campaign_draft(conn, _raw(existing_brand_id=brand["id"], brand_name=None), TODAY, THRESHOLDS)
    assert draft["campaign"]["existing_brand_id"] == brand["id"]
    assert draft["campaign"]["brand_name"] == brand["name"]


def test_unknown_existing_brand_id_falls_back_with_warning(conn):
    draft = normalize_campaign_draft(conn, _raw(existing_brand_id=999999), TODAY, THRESHOLDS)
    assert draft["campaign"]["existing_brand_id"] is None
    assert any(w["field"] == "campaign.existing_brand_id" for w in draft["warnings"])


def test_creator_blocks_use_intake_normalize_draft(conn):
    """Each creators[i] IS app/intake.py's own per-creator draft shape — same
    estimated-metrics honesty, same handle normalization, same warnings."""
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    assert len(draft["creators"]) == 1
    creator = draft["creators"][0]["creator"]
    assert creator["handle"] == "freshcreator"
    assert creator["metrics_source"] == "estimated"


def test_no_creators_warns(conn):
    raw = _raw()
    raw["creators"] = []
    draft = normalize_campaign_draft(conn, raw, TODAY, THRESHOLDS)
    assert any(w["field"] == "creators" for w in draft["warnings"])


def test_too_many_creators_truncated_with_warning(conn):
    raw = _raw()
    max_c = THRESHOLDS["campaign_intake"]["max_creators_per_brief"]
    raw["creators"] = raw["creators"] * (max_c + 5)
    draft = normalize_campaign_draft(conn, raw, TODAY, THRESHOLDS)
    assert len(draft["creators"]) == max_c
    assert any(w["field"] == "creators" for w in draft["warnings"])


# --- validate_campaign_draft ------------------------------------------------


def test_valid_draft_has_no_blocking_errors(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    assert validate_campaign_draft(draft, THRESHOLDS) == []


def test_missing_name_is_blocking(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["campaign"]["name"] = ""
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "campaign.name" and e["blocking"] for e in errors)


def test_missing_brand_is_blocking_without_existing_id(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["campaign"]["brand_name"] = ""
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "campaign.brand_name" and e["blocking"] for e in errors)


def test_disclosure_can_never_be_blank(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["campaign"]["required_disclosure"] = ""
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "campaign.required_disclosure" and e["blocking"] for e in errors)


def test_duration_out_of_bounds_is_blocking(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["campaign"]["duration_days"] = THRESHOLDS["campaign_intake"]["max_duration_days"] + 1
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "campaign.duration_days" and e["blocking"] for e in errors)


def test_days_running_exceeding_duration_is_blocking(conn):
    draft = normalize_campaign_draft(conn, _raw(duration_days=10, days_running=5), TODAY, THRESHOLDS)
    draft["campaign"]["days_running"] = 20  # tampered beyond the campaign's own duration
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "campaign.days_running" and e["blocking"] for e in errors)


def test_no_creators_is_blocking(conn):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["creators"] = []
    errors = validate_campaign_draft(draft, THRESHOLDS)
    assert any(e["field"] == "creators" and e["blocking"] for e in errors)


def test_bad_creator_deliverable_surfaces_prefixed_field(conn):
    """A blocking error inside creators[0]'s own deliverables (reused from
    intake.validate_draft) must surface with a creators[i]. prefix, not get
    silently swallowed at campaign scope."""
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["creators"][0]["deliverables"][0]["due_day"] = 999  # beyond duration_days
    errors = validate_campaign_draft(draft, THRESHOLDS)
    matching = [e for e in errors if e["field"].startswith("creators[0].deliverables[0].due_day")]
    assert matching and matching[0]["blocking"]
