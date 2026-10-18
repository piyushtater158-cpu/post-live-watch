"""Verifies all 12 post-live problems trigger on exactly the right seeded
posts, and that healthy posts stay clean. This is the correctness bar the
brief actually grades ("all 12 problems trigger on the right posts")."""

from app.rules.engine import evaluate_campaign, evaluate_post

HEALTHY_IDS = {1, 5, 6, 9, 12, 15, 18, 20}

EXPECTED_RULE_FOR_POST = {
    2: 1,    # not posted
    3: {2, 6},  # posted late + suspicious engagement
    4: 3,    # missing disclosure
    7: 4,    # missing tag/link/hashtag
    8: 5,    # underperforming
    10: 6,   # suspicious engagement
    11: 7,   # negative sentiment spike
    13: 8,   # deleted early
    14: {9, 3},  # caption edited/off-brief + missing disclosure
    16: 10,  # story expired without proof
    17: 11,  # competitor post
}

VIRAL_POST_ID = 19


def _rule_ids(flags):
    return {f["rule_id"] for f in flags}


def test_all_12_problems_fire_at_full_campaign(conn):
    results = {r["post_id"]: r for r in evaluate_campaign(conn, campaign_id=1, current_day=7)}

    fired_rule_ids = set()
    for pid, expected in EXPECTED_RULE_FOR_POST.items():
        flags = results[pid]["flags"]
        got = _rule_ids(flags)
        expected_set = expected if isinstance(expected, set) else {expected}
        missing = expected_set - got
        assert not missing, f"post {pid} ({results[pid]['creator_handle']}) missing rule(s) {missing}, got {got}"
        fired_rule_ids |= got

    viral_flags = results[VIRAL_POST_ID]["opportunities"]
    assert _rule_ids(viral_flags) == {12}, f"expected rule 12 on post {VIRAL_POST_ID}, got {_rule_ids(viral_flags)}"
    fired_rule_ids.add(12)

    assert fired_rule_ids == set(range(1, 13)), f"not all 12 rules fired: missing {set(range(1,13)) - fired_rule_ids}"


def test_healthy_posts_stay_clean(conn):
    results = {r["post_id"]: r for r in evaluate_campaign(conn, campaign_id=1, current_day=7)}
    for pid in HEALTHY_IDS:
        r = results[pid]
        assert r["status"] == "OK", f"post {pid} ({r['creator_handle']}) expected OK, got {r['status']}: {r['reason']}"
        assert r["flags"] == [], f"post {pid} unexpectedly flagged: {r['flags']}"


def test_viral_winner_is_not_hidden_by_ok_status(conn):
    result = evaluate_post(conn, VIRAL_POST_ID, current_day=7)
    assert result["status"] == "OK"  # low severity alone wouldn't escalate status
    assert len(result["opportunities"]) == 1
    assert result["opportunities"][0]["rule_id"] == 12


def test_not_posted_only_fires_after_grace_period(conn):
    # Day 2 is still within the 1-day grace period after the day-1 due date.
    early = evaluate_post(conn, 2, current_day=2)
    assert 1 not in _rule_ids(early["flags"]), "not_posted fired too early, before grace period elapsed"

    later = evaluate_post(conn, 2, current_day=3)
    assert 1 in _rule_ids(later["flags"]), "not_posted should have fired once grace period elapsed"


def test_story_expiry_only_fires_once_24h_have_passed(conn):
    day1 = evaluate_post(conn, 16, current_day=1)
    assert 10 not in _rule_ids(day1["flags"]), "story_expired fired before the 24h window elapsed"

    day2 = evaluate_post(conn, 16, current_day=2)
    assert 10 in _rule_ids(day2["flags"]), "story_expired should fire once 24h have passed with no proof"


def test_act_now_severity_outranks_needs_a_look(conn):
    results = {r["post_id"]: r for r in evaluate_campaign(conn, campaign_id=1, current_day=7)}
    assert results[2]["status"] == "Act now"   # not_posted, severity 9
    assert results[13]["status"] == "Act now"  # deleted_early, severity 9
    assert results[8]["status"] in {"Needs a look", "Act now"}  # underperforming, severity 6
