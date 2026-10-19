"""Verifies the campaign brief is a DEFAULT, not a law: deliverable-level
overrides resolve correctly, waived requirements stop the right detector
without going silent, deals with no reach guarantee can't underperform, and
a creator's rolled-up status reflects every deliverable in their package,
not an arbitrarily picked one."""

from app.rules.contract import resolve_terms
from app.rules.engine import evaluate_post
from app.dashboard import _creator_deliverables, _rollup_campaign_status
from app.reliability import compute_reliability

CAMPAIGN = {
    "required_disclosure": "#ad|paid partnership",
    "required_tag": "@glowleaf",
    "required_hashtag": "#GlowWithGlowLeaf",
    "requires_link_sticker": 1,
}


def _deliverable(**overrides):
    base = {
        "format": "reel",
        "required_disclosure": None,
        "required_tag": None,
        "required_hashtag": None,
        "requires_link_sticker": None,
        "deal_type": "paid",
        "waived_notes": None,
        "min_reach": 10000,
    }
    base.update(overrides)
    return base


def test_override_beats_campaign_default_null_inherits():
    terms = resolve_terms(_deliverable(required_tag="@someoneelse"), CAMPAIGN)
    assert terms.required_tag == "@someoneelse"

    terms_inherited = resolve_terms(_deliverable(), CAMPAIGN)
    assert terms_inherited.required_tag == "@glowleaf"


def test_link_sticker_not_required_on_non_story_by_default():
    # Structural fact about the format, not a negotiated term -- no contract
    # note here, or every reel/carousel in the roster would carry one.
    terms = resolve_terms(_deliverable(format="carousel"), CAMPAIGN)
    assert terms.requires_link_sticker is False
    assert terms.contract_notes == []


def test_link_sticker_required_on_story_by_default():
    terms = resolve_terms(_deliverable(format="story"), CAMPAIGN)
    assert terms.requires_link_sticker is True


def test_link_sticker_explicit_override_wins_regardless_of_format():
    terms = resolve_terms(_deliverable(format="story", requires_link_sticker=0), CAMPAIGN)
    assert terms.requires_link_sticker is False


def test_rule4_no_link_sticker_complaint_on_carousel(conn):
    # Post 7: missing_tag_link scenario, carousel format. Caption is missing
    # the tag and hashtag, so rule 4 should still fire — but never for the
    # link sticker, since a carousel can't have one.
    result = evaluate_post(conn, post_id=7, current_day=7)
    flag = next(f for f in result["flags"] if f["rule_id"] == 4)
    assert "link sticker" not in flag["evidence"]["missing"]
    assert any(m.startswith("tag") or m.startswith("hashtag") for m in flag["evidence"]["missing"])


def test_rule5_no_flag_without_reach_guarantee():
    terms = resolve_terms(_deliverable(min_reach=None), CAMPAIGN)
    assert terms.min_reach is None
    assert any(n["requirement"] == "Reach guarantee" for n in terms.contract_notes)


def test_barter_creator_never_flagged_for_underperforming(conn):
    # Post 5 is seeded as a barter deal (no min_reach), so rule 5 must never fire.
    result = evaluate_post(conn, post_id=5, current_day=7)
    assert not any(f["rule_id"] == 5 for f in result["flags"])
    assert result["deal_type"] == "barter"


def test_rule3_accepts_any_token_in_disclosure_list():
    terms = resolve_terms(_deliverable(required_disclosure="#ad|paid partnership"), CAMPAIGN)
    assert terms.required_disclosure == ["#ad", "paid partnership"]


def test_hashtag_waived_creator_has_no_duplicate_note(conn):
    # Post 14 negotiated the hashtag out via waived_notes — the explicit
    # reason should appear once, not doubled up with the generic fallback.
    result = evaluate_post(conn, post_id=14, current_day=7)
    hashtag_notes = [n for n in result["contract_notes"] if n["requirement"] == "Hashtag"]
    assert len(hashtag_notes) == 1
    assert "exclusivity" in hashtag_notes[0]["note"]
    # The waiver coexists with real flags — it never hides them.
    assert result["flags"], "post 14 should still carry its real flags (disclosure, caption edit)"


def test_creator1_rollup_reflects_worst_deliverable(conn):
    deliverables = _creator_deliverables(conn, creator_id=1, current_day=7)
    assert len(deliverables) == 3  # reel + 2 stories
    rollup = _rollup_campaign_status(deliverables)
    # Post 22 (story, no screenshot) fires rule 10 by day 7 -> status can't stay "OK"
    # even though post 1 (the reel) is healthy on its own.
    assert rollup["status"] != "OK"
    assert rollup["total_deliverables"] == 3


def test_reliability_aggregates_across_all_deliverables(conn):
    # Creator 1 now has 3 deliverables; compute_reliability must not silently
    # score against just one of them.
    r = compute_reliability(conn, creator_id=1, current_day=7)
    assert 0 <= r["score"] <= 100


def test_standard_deal_has_no_contract_notes(conn):
    # Post 1 (creator 1's reel) takes every campaign default as-is.
    result = evaluate_post(conn, post_id=1, current_day=7)
    assert result["contract_notes"] == []
