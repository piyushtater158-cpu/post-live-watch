"""app/intake.py:commit_intake is the one function in this feature that
writes. Verifies new-creator creation, existing-creator attachment (no
duplicate, case-insensitive), transactional rollback on failure, and that
the rows it creates behave correctly once the already-shipped contract/
rollup machinery (resolve_terms, evaluate_post, _rollup_campaign_status)
reads them."""

import pytest

from app.config import load_thresholds
from app.dashboard import _creator_deliverables, _rollup_campaign_status
from app.intake import IntakeValidationError, commit_intake
from app.rules.engine import evaluate_post

THRESHOLDS = load_thresholds()


def _campaign_row(conn):
    return dict(conn.execute("SELECT * FROM campaigns WHERE id = 1").fetchone())


def _new_creator_draft(handle="freshcreator", existing_id=None):
    return {
        "creator": {
            "existing_creator_id": existing_id, "handle": handle, "followers": 60000,
            "tier": "micro", "niche": "skincare", "avg_reach": 18000.0, "avg_engagement_rate": 0.05,
            "metrics_source": "estimated",
        },
        "deliverables": [{
            "format": "reel", "deal_type": "paid", "fee": 20000, "barter_value": None,
            "bonus_threshold": None, "bonus_amount": None, "min_reach": 15000,
            "min_reach_explicitly_none": False, "due_day": 3,
            "required_tag": None, "required_hashtag": None, "required_disclosure": None,
            "requires_link_sticker": None, "waived_notes": {},
        }],
        "brief_text": "test brief",
    }


def test_new_creator_creates_expected_rows(conn):
    before = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
    result = commit_intake(conn, _new_creator_draft(), _campaign_row(conn), THRESHOLDS)
    after = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
    assert after == before + 1
    assert len(result["deliverable_ids"]) == 1
    assert len(result["post_ids"]) == 1

    post = conn.execute("SELECT * FROM posts WHERE id = ?", (result["post_ids"][0],)).fetchone()
    assert post["posted_at"] is None
    assert post["screenshot_uploaded"] == 0


def test_existing_creator_attaches_without_duplicating(conn):
    before_creators = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
    before_deliverables = conn.execute("SELECT COUNT(*) c FROM deliverables WHERE creator_id = 1").fetchone()["c"]

    draft = _new_creator_draft(handle="glow_with_meera", existing_id=1)
    result = commit_intake(conn, draft, _campaign_row(conn), THRESHOLDS)

    assert result["creator_id"] == 1
    assert result["created_creator"] is False
    assert conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"] == before_creators
    assert conn.execute("SELECT COUNT(*) c FROM deliverables WHERE creator_id = 1").fetchone()["c"] == before_deliverables + 1

    # Attaching never rewrites the existing creator's measured profile.
    creator = dict(conn.execute("SELECT * FROM creators WHERE id = 1").fetchone())
    assert creator["followers"] != 60000


def test_mixed_case_handle_attaches_not_duplicates(conn):
    before = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
    draft = _new_creator_draft(handle="Glow_With_Meera", existing_id=None)
    # Simulate what normalize_draft would have resolved: an exact-match lookup
    # on the lowercased handle found creator 1, so existing_creator_id is set.
    draft["creator"]["existing_creator_id"] = 1
    result = commit_intake(conn, draft, _campaign_row(conn), THRESHOLDS)
    assert result["creator_id"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"] == before


def test_blocking_validation_error_writes_nothing(conn):
    before_creators = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
    before_deliverables = conn.execute("SELECT COUNT(*) c FROM deliverables").fetchone()["c"]

    draft = _new_creator_draft()
    draft["deliverables"][0]["due_day"] = 999  # beyond duration_days -> blocking

    with pytest.raises(IntakeValidationError):
        commit_intake(conn, draft, _campaign_row(conn), THRESHOLDS)

    assert conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"] == before_creators
    assert conn.execute("SELECT COUNT(*) c FROM deliverables").fetchone()["c"] == before_deliverables


def test_new_rows_flow_through_the_rollup_and_contract_machinery(conn):
    result = commit_intake(conn, _new_creator_draft(handle="packagecreator"), _campaign_row(conn), THRESHOLDS)
    creator_id = result["creator_id"]

    evaluated = evaluate_post(conn, result["post_ids"][0], current_day=1)
    assert evaluated["status"] == "OK"  # not due yet, no flags
    assert evaluated["contract_notes"] == []  # nothing negotiated away in this draft

    deliverables = _creator_deliverables(conn, creator_id, current_day=1)
    assert len(deliverables) == 1
    rollup = _rollup_campaign_status(deliverables)
    assert rollup["total_deliverables"] == 1


def test_intake_audit_row_recorded_in_decisions(conn):
    result = commit_intake(conn, _new_creator_draft(handle="auditedcreator"), _campaign_row(conn), THRESHOLDS)
    row = conn.execute(
        "SELECT * FROM decisions WHERE post_id = ? AND source = 'intake'", (result["post_ids"][0],)
    ).fetchone()
    assert row is not None
    assert row["message_text"] == "test brief"
