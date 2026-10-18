from app.reliability import compute_reliability


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
