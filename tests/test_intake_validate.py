"""app/intake.py:validate_draft is pure (no DB) — every one of these builds a
hand-crafted draft dict and checks the specific blocking/non-blocking rule
that matters most for keeping a wrong AI/fallback parse from silently
reaching the rules engine."""

from app.config import load_thresholds
from app.intake import validate_draft

THRESHOLDS = load_thresholds()
CAMPAIGN = {"duration_days": 7, "start_date": "2026-09-01T09:00:00"}


def _clean_draft(**overrides):
    draft = {
        "creator": {
            "existing_creator_id": None, "handle": "newcreator", "followers": 50000,
            "tier": "micro", "niche": "skincare", "avg_reach": 15000.0, "avg_engagement_rate": 0.05,
        },
        "deliverables": [{
            "format": "reel", "deal_type": "paid", "fee": 20000, "barter_value": None,
            "bonus_threshold": None, "bonus_amount": None, "min_reach": 15000,
            "min_reach_explicitly_none": False, "due_day": 3,
            "required_tag": None, "required_hashtag": None, "required_disclosure": None,
            "requires_link_sticker": None, "waived_notes": {},
        }],
    }
    draft.update(overrides)
    return draft


def _blocking(draft):
    return [e for e in validate_draft(draft, CAMPAIGN, THRESHOLDS) if e["blocking"]]


def test_clean_draft_has_no_blocking_errors():
    assert _blocking(_clean_draft()) == []


def test_bad_format_blocks():
    d = _clean_draft()
    d["deliverables"][0]["format"] = "igtv"
    assert any("format" in e["field"] for e in _blocking(d))


def test_bad_deal_type_blocks():
    d = _clean_draft()
    d["deliverables"][0]["deal_type"] = "freebie"
    assert any("deal_type" in e["field"] for e in _blocking(d))


def test_negative_fee_blocks():
    d = _clean_draft()
    d["deliverables"][0]["fee"] = -500
    assert any("fee" in e["field"] for e in _blocking(d))


def test_due_day_zero_blocks():
    d = _clean_draft()
    d["deliverables"][0]["due_day"] = 0
    assert any("due_day" in e["field"] for e in _blocking(d))


def test_due_day_beyond_campaign_blocks():
    d = _clean_draft()
    d["deliverables"][0]["due_day"] = 99
    assert any("due_day" in e["field"] for e in _blocking(d))


def test_too_many_deliverables_blocks():
    d = _clean_draft()
    one = d["deliverables"][0]
    d["deliverables"] = [dict(one) for _ in range(THRESHOLDS["intake"]["max_deliverables_per_brief"] + 1)]
    assert any(e["field"] == "deliverables" for e in _blocking(d))


def test_disclosure_cannot_be_waived():
    d = _clean_draft()
    d["deliverables"][0]["required_disclosure"] = ""
    assert any("required_disclosure" in e["field"] for e in _blocking(d))


def test_junk_waived_notes_key_blocks():
    d = _clean_draft()
    d["deliverables"][0]["waived_notes"] = {"min_reach": "nope"}
    assert any("waived_notes" in e["field"] for e in _blocking(d))


def test_zero_avg_reach_blocks_for_new_creator():
    d = _clean_draft()
    d["creator"]["avg_reach"] = 0
    assert any("avg_reach" in e["field"] for e in _blocking(d))


def test_bad_handle_blocks_for_new_creator():
    d = _clean_draft()
    d["creator"]["handle"] = "N"  # too short
    assert any("handle" in e["field"] for e in _blocking(d))


def test_existing_creator_skips_profile_validation():
    d = _clean_draft()
    d["creator"] = {"existing_creator_id": 1, "handle": "glow_with_meera"}
    assert _blocking(d) == []


def test_barter_with_fee_blocks():
    d = _clean_draft()
    d["deliverables"][0]["deal_type"] = "barter"
    d["deliverables"][0]["fee"] = 10000
    assert any("fee" in e["field"] for e in _blocking(d))


def test_paid_without_fee_blocks():
    d = _clean_draft()
    d["deliverables"][0]["fee"] = None
    assert any("fee" in e["field"] for e in _blocking(d))


def test_barter_without_barter_value_is_warning_not_blocking():
    d = _clean_draft()
    d["deliverables"][0]["deal_type"] = "barter"
    d["deliverables"][0]["fee"] = None
    d["deliverables"][0]["barter_value"] = None
    all_errors = validate_draft(d, CAMPAIGN, THRESHOLDS)
    assert any("barter_value" in e["field"] and not e["blocking"] for e in all_errors)
    assert not any("barter_value" in e["field"] and e["blocking"] for e in all_errors)
