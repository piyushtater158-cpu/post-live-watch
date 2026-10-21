"""app/campaign_intake.py:commit_campaign is the one function in this module
that writes. Verifies new-brand/new-campaign creation, existing-brand
attachment, multi-creator writes (existing + brand-new creator together),
transactional rollback spanning the WHOLE campaign (not just one creator),
and that get_campaign_day reports the right day immediately for an
in-flight campaign."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.campaign_intake import CampaignValidationError, commit_campaign, normalize_campaign_draft
from app.config import load_thresholds
from app.db import get_campaign_day

THRESHOLDS = load_thresholds()
TODAY = datetime.now()

TABLES = ("decisions", "posts", "deliverables", "creators", "campaigns", "brands")


def _raw(**campaign_overrides):
    return {
        "source": "form", "brief_text": "test brief",
        "campaign": {"name": "Commit Test Launch", "brand_name": "CommitTestBrand", **campaign_overrides},
        "creators": [
            {"creator": {"handle": "glow_with_meera", "existing_creator_id": 1}, "deliverables": [
                {"format": "reel", "deal_type": "paid", "fee": 10000, "min_reach": 5000, "due_day": 3},
            ]},
            {"creator": {"handle": "brandnewcommitcreator", "followers": 30000, "tier": "micro", "niche": "fitness"},
             "deliverables": [
                {"format": "story", "deal_type": "barter", "barter_value": 2000, "min_reach": None,
                 "min_reach_explicitly_none": True, "due_day": 2},
            ]},
        ],
    }


@pytest.fixture
def high_water(conn):
    before = {t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"] for t in TABLES}
    yield before
    for t in TABLES:
        conn.execute(f"DELETE FROM {t} WHERE id > ?", (before[t],))
    conn.commit()


def test_new_campaign_creates_brand_and_campaign(conn, high_water):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    result = commit_campaign(conn, draft, THRESHOLDS)

    campaign = conn.execute("SELECT * FROM campaigns WHERE id = ?", (result["campaign_id"],)).fetchone()
    assert campaign["name"] == "Commit Test Launch"
    assert campaign["day_override"] is None  # live clock
    assert campaign["metrics_provider"] == "manual"
    assert campaign["status"] == "active"

    brand = conn.execute("SELECT * FROM brands WHERE id = ?", (result["brand_id"],)).fetchone()
    assert brand["name"] == "CommitTestBrand"


def test_existing_and_new_creator_both_written(conn, high_water):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    result = commit_campaign(conn, draft, THRESHOLDS)

    existing_result, new_result = result["creators"]
    assert existing_result["creator_id"] == 1 and existing_result["created_creator"] is False
    assert new_result["created_creator"] is True

    deliverables = conn.execute(
        "SELECT COUNT(*) c FROM deliverables WHERE campaign_id = ?", (result["campaign_id"],)
    ).fetchone()["c"]
    assert deliverables == 2


def test_existing_brand_reused_without_duplicating(conn, high_water):
    brand = conn.execute("SELECT id FROM brands LIMIT 1").fetchone()
    draft = normalize_campaign_draft(conn, _raw(existing_brand_id=brand["id"], brand_name=None), TODAY, THRESHOLDS)
    before_brands = conn.execute("SELECT COUNT(*) c FROM brands").fetchone()["c"]

    result = commit_campaign(conn, draft, THRESHOLDS)

    assert result["brand_id"] == brand["id"]
    assert conn.execute("SELECT COUNT(*) c FROM brands").fetchone()["c"] == before_brands


def test_in_flight_campaign_reports_correct_day_immediately(conn, high_water):
    draft = normalize_campaign_draft(conn, _raw(duration_days=14, days_running=6), TODAY, THRESHOLDS)
    result = commit_campaign(conn, draft, THRESHOLDS)
    assert get_campaign_day(conn, result["campaign_id"]) == 6


def test_blocking_validation_error_writes_nothing(conn, high_water):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    draft["campaign"]["name"] = ""  # blocking

    with pytest.raises(CampaignValidationError):
        commit_campaign(conn, draft, THRESHOLDS)

    assert conn.execute("SELECT COUNT(*) c FROM campaigns WHERE id > ?", (high_water["campaigns"],)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM brands WHERE id > ?", (high_water["brands"],)).fetchone()["c"] == 0


def test_a_bad_second_creator_rolls_back_the_whole_campaign(conn, high_water):
    """The actual point of this module's single transaction: creator 2's
    failure must not leave creator 1, the campaign, or the brand half-written."""
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    # Tamper with the second creator's deliverable AFTER validation would have
    # passed on the pre-tamper draft — mirrors a stale/forged hidden field,
    # exactly like app/intake.py's own "re-validates inside the transaction" note.
    draft["creators"][1]["deliverables"][0]["due_day"] = 999

    with pytest.raises(CampaignValidationError):
        commit_campaign(conn, draft, THRESHOLDS)

    assert conn.execute("SELECT COUNT(*) c FROM campaigns WHERE id > ?", (high_water["campaigns"],)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM brands WHERE id > ?", (high_water["brands"],)).fetchone()["c"] == 0
    assert conn.execute(
        "SELECT COUNT(*) c FROM creators WHERE handle = 'brandnewcommitcreator'"
    ).fetchone()["c"] == 0


def test_intake_audit_rows_recorded_for_every_creator(conn, high_water):
    draft = normalize_campaign_draft(conn, _raw(), TODAY, THRESHOLDS)
    result = commit_campaign(conn, draft, THRESHOLDS)
    all_post_ids = [pid for cr in result["creators"] for pid in cr["post_ids"]]
    rows = conn.execute(
        f"SELECT * FROM decisions WHERE source = 'intake' AND post_id IN ({','.join('?' * len(all_post_ids))})",
        all_post_ids,
    ).fetchall()
    assert len(rows) == len(all_post_ids)
    assert all(r["message_text"] == "test brief" for r in rows)
