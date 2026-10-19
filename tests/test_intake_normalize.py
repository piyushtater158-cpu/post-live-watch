"""app/intake.py:normalize_draft's handling of a new creator's averages: the
follower-count estimate stays labelled 'estimated' unless the AM actually
typed a different number, and a percentage-style engagement rate is converted."""

from app.config import load_thresholds
from app.intake import campaign_row, estimate_creator_metrics, normalize_draft

THRESHOLDS = load_thresholds()


def _raw(**creator):
    return {
        "source": "template", "brief_text": "x",
        "creator": {"handle": "brand_new_creator", "followers": 60000, "tier": "micro", "niche": "skincare", **creator},
        "deliverables": [{"format": "reel", "deal_type": "paid", "fee": 1000, "min_reach": 5000, "due_day": 2}],
    }


def test_untouched_estimate_stays_estimated(conn):
    draft = normalize_draft(conn, _raw(), campaign_row(conn), 1, THRESHOLDS)
    est_reach, _ = estimate_creator_metrics(60000, "micro", THRESHOLDS)
    assert draft["creator"]["metrics_source"] == "estimated"
    assert draft["creator"]["avg_reach"] == round(est_reach, 1)


def test_resubmitted_estimate_from_edit_form_stays_estimated(conn):
    first = normalize_draft(conn, _raw(), campaign_row(conn), 1, THRESHOLDS)["creator"]
    again = normalize_draft(conn, _raw(avg_reach=first["avg_reach"], avg_engagement_rate=first["avg_engagement_rate"]),
                            campaign_row(conn), 1, THRESHOLDS)
    assert again["creator"]["metrics_source"] == "estimated"


def test_am_typed_reach_is_am_entered(conn):
    draft = normalize_draft(conn, _raw(avg_reach=31000), campaign_row(conn), 1, THRESHOLDS)
    assert draft["creator"]["metrics_source"] == "am_entered"
    assert draft["creator"]["avg_reach"] == 31000


def test_percentage_engagement_rate_is_converted_with_warning(conn):
    draft = normalize_draft(conn, _raw(avg_engagement_rate=4.5), campaign_row(conn), 1, THRESHOLDS)
    assert draft["creator"]["avg_engagement_rate"] == 0.045
    assert any(w["field"] == "creator.avg_engagement_rate" for w in draft["warnings"])
