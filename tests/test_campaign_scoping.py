"""Regression guard for the bug this plan exists to fix: dashboard.py and
reliability.py used to query a creator's deliverables with NO campaign filter,
which was only ever correct because exactly one campaign existed. This test
enrolls creator 1 (glow_with_meera, already in the seeded campaign 1) into a
SECOND campaign with its own bad flag, and asserts campaign 1's queue,
overview, rollup and reliability score are completely unaffected by it — and
that campaign 2's own view sees only its own deliverable.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.dashboard import (
    _creator_deliverables,
    get_creator_package,
    get_creator_profile,
    get_flag_queue,
    get_overview,
)
from app.reliability import compute_reliability

CREATOR_1 = 1  # glow_with_meera — campaign 1's healthy creator (post 1)
ISO = "%Y-%m-%dT%H:%M:%S"


@pytest.fixture
def second_campaign_overlap(conn):
    """Campaign 2: a different brand, a short simulated run that has already
    ended, with creator 1 signed to a deliverable they never posted — a
    deliberate 'Act now' (rule 1: Not posted) flag that must stay invisible
    to campaign 1's own views."""
    high = {
        t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"]
        for t in ("brands", "campaigns", "deliverables", "posts")
    }
    start = datetime(2026, 1, 1, 9, 0, 0)

    brand_cur = conn.execute("INSERT INTO brands (name, product) VALUES ('OtherBrand', 'Sunscreen')")
    brand_id = brand_cur.lastrowid
    camp_cur = conn.execute(
        "INSERT INTO campaigns (brand_id, name, start_date, duration_days, required_disclosure, "
        "required_tag, required_hashtag, requires_link_sticker, banned_claims, day_override, status) "
        "VALUES (?, 'OtherBrand Launch', ?, 7, '#ad', '@otherbrand', '#OtherGlow', 1, '[]', 7, 'active')",
        (brand_id, start.strftime(ISO)),
    )
    campaign_id = camp_cur.lastrowid
    deliv_cur = conn.execute(
        "INSERT INTO deliverables (campaign_id, creator_id, format, fee, promised_date, min_reach) "
        "VALUES (?, ?, 'reel', 30000, ?, 20000)",
        (campaign_id, CREATOR_1, start.strftime(ISO)),
    )
    deliverable_id = deliv_cur.lastrowid
    post_cur = conn.execute(
        "INSERT INTO posts (deliverable_id, posted_at, link_sticker_present, is_story, screenshot_uploaded) "
        "VALUES (?, NULL, 0, 0, 0)",
        (deliverable_id,),
    )
    post_id = post_cur.lastrowid
    conn.commit()

    yield {"campaign_id": campaign_id, "deliverable_id": deliverable_id, "post_id": post_id}

    for table in ("posts", "deliverables", "campaigns", "brands"):
        conn.execute(f"DELETE FROM {table} WHERE id > ?", (high[table],))
    conn.commit()


def test_creator_deliverables_filtered_by_campaign(conn, second_campaign_overlap):
    camp1_deliverables = _creator_deliverables(conn, campaign_id=1, creator_id=CREATOR_1, current_day=7)
    assert len(camp1_deliverables) == 3  # unchanged: reel + 2 stories, same as test_contract.py's baseline
    assert all(d["post_id"] != second_campaign_overlap["post_id"] for d in camp1_deliverables)

    camp2_deliverables = _creator_deliverables(conn, campaign_id=second_campaign_overlap["campaign_id"],
                                                creator_id=CREATOR_1, current_day=7)
    assert len(camp2_deliverables) == 1
    assert camp2_deliverables[0]["post_id"] == second_campaign_overlap["post_id"]
    assert camp2_deliverables[0]["status"] == "Act now"  # the deliberate Not-posted flag


def test_campaign1_queue_excludes_other_campaigns_flags(conn, second_campaign_overlap):
    cards = get_flag_queue(conn, campaign_id=1, current_day=7, ai_enabled=False)
    assert all(c["post_id"] != second_campaign_overlap["post_id"] for c in cards)


def test_campaign1_overview_unaffected_by_other_campaign(conn, second_campaign_overlap):
    before = get_overview(conn, campaign_id=1, current_day=7)
    # Re-fetch after the fixture's insert — campaign 1's own numbers must be identical
    # whether or not creator 1 has a second, unrelated campaign with a live flag.
    after = get_overview(conn, campaign_id=1, current_day=7)
    assert before["total_due"] == after["total_due"]
    assert before["by_status"] == after["by_status"]
    assert before["total_reach"] == after["total_reach"]


def test_reliability_score_excludes_other_campaign(conn, second_campaign_overlap):
    """The actual bug this regression guards: campaign 2's Not-posted flag must
    not drag down creator 1's campaign-1 reliability score."""
    scoped = compute_reliability(conn, campaign_id=1, creator_id=CREATOR_1, current_day=7)

    # Remove the fixture's campaign-2 row and recompute — if campaign_id filtering
    # were missing, the two numbers would differ (campaign 2's flag would count).
    conn.execute("DELETE FROM posts WHERE id = ?", (second_campaign_overlap["post_id"],))
    conn.commit()
    without_overlap = compute_reliability(conn, campaign_id=1, creator_id=CREATOR_1, current_day=7)

    assert scoped["score"] == without_overlap["score"]
    assert scoped["campaigns_considered"] == without_overlap["campaigns_considered"]
    assert scoped["on_time_rate"] == without_overlap["on_time_rate"]
    # restore for the fixture's own teardown (deliverable row stays, cascade-free)
    conn.execute(
        "INSERT INTO posts (id, deliverable_id, posted_at, link_sticker_present, is_story, screenshot_uploaded) "
        "VALUES (?, ?, NULL, 0, 0, 0)",
        (second_campaign_overlap["post_id"], second_campaign_overlap["deliverable_id"]),
    )
    conn.commit()


def test_creator_package_scoped_to_requested_campaign(conn, second_campaign_overlap):
    pkg1 = get_creator_package(conn, campaign_id=1, creator_id=CREATOR_1, current_day=7)
    assert pkg1["current_campaign"]["total_deliverables"] == 3

    pkg2 = get_creator_package(conn, campaign_id=second_campaign_overlap["campaign_id"],
                                creator_id=CREATOR_1, current_day=7)
    assert pkg2["current_campaign"]["total_deliverables"] == 1
    assert pkg2["current_campaign"]["status"] == "Act now"


def test_other_campaigns_listed_on_profile_not_folded_in(conn, second_campaign_overlap):
    profile = get_creator_profile(conn, campaign_id=1, creator_id=CREATOR_1, current_day=7)
    assert profile["current_campaign"]["total_deliverables"] == 3  # not 4 — the other campaign is excluded here
    other = {o["campaign_id"]: o for o in profile["other_campaigns"]}
    assert second_campaign_overlap["campaign_id"] in other
    assert other[second_campaign_overlap["campaign_id"]]["status"] == "Act now"
