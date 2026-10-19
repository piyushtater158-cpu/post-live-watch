import pytest

from app.config import load_thresholds
from app.intake import campaign_row, commit_intake
from app.reliability import compute_reliability

TABLES = ("decisions", "posts", "deliverables", "creators")


@pytest.fixture
def new_barter_creator(conn):
    """A brand-new intake creator with one barter (no reach guarantee) reel due on day 3;
    rows are removed afterwards so the shared seeded DB stays as the other suites expect."""
    high = {t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"] for t in TABLES}
    draft = {
        "brief_text": "test",
        "creator": {"existing_creator_id": None, "handle": "brand_new_barter", "followers": 50000, "tier": "micro",
                    "niche": "skincare", "avg_reach": 16500.0, "avg_engagement_rate": 0.05, "metrics_source": "estimated"},
        "deliverables": [{"format": "reel", "deal_type": "barter", "fee": None, "barter_value": 5000, "bonus_threshold": None,
                          "bonus_amount": None, "min_reach": None, "min_reach_explicitly_none": True, "due_day": 3,
                          "required_tag": None, "required_hashtag": None, "required_disclosure": None,
                          "requires_link_sticker": None, "waived_notes": {}}],
    }
    result = commit_intake(conn, draft, campaign_row(conn), load_thresholds())
    yield result["creator_id"]
    for t in TABLES:
        conn.execute(f"DELETE FROM {t} WHERE id > ?", (high[t],))
    conn.commit()


def test_new_creator_with_nothing_due_has_no_score(conn, new_barter_creator):
    r = compute_reliability(conn, new_barter_creator, current_day=1)
    assert r["score"] is None and r["campaigns_considered"] == 0
    assert r["book_again_hint"].startswith("New")


def test_barter_deal_is_not_scored_as_zero_performance(conn, new_barter_creator):
    r = compute_reliability(conn, new_barter_creator, current_day=5)  # due day 3 + 1-day grace: now "not posted"
    assert r["campaigns_considered"] == 1
    assert r["avg_performance_ratio"] is None
    assert r["on_time_rate"] == 0.0 and r["score"] is not None


def test_reliability_score_in_range_for_all_creators(conn):
    for creator_id in range(1, 21):
        r = compute_reliability(conn, creator_id, current_day=7)
        assert 0 <= r["score"] <= 100
        assert r["campaigns_considered"] >= 1
        assert r["book_again_hint"] in {
            "Yes — book again", "Maybe — review flags first", "Caution — review before rebooking",
        }


def test_not_posted_creator_scores_lower_than_healthy_creator(conn):
    ghosted = compute_reliability(conn, creator_id=2, current_day=7)   # not_posted
    healthy = compute_reliability(conn, creator_id=1, current_day=7)   # healthy
    assert ghosted["score"] < healthy["score"]
