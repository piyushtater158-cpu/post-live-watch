"""app/db.py:get_campaign_day — the per-campaign clock. day_override set means
the simulator owns the day; day_override NULL means it's derived from
start_date against wall-clock time, clamped to [1, duration_days] either way."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db import get_campaign_day

ISO = "%Y-%m-%dT%H:%M:%S"


@pytest.fixture
def restore_campaign1(conn):
    """Campaign 1 is the shared seeded campaign every other test suite assumes
    is on the simulated clock at day_override=7 — snapshot and restore it."""
    before = dict(conn.execute("SELECT start_date, duration_days, day_override FROM campaigns WHERE id = 1").fetchone())
    yield
    conn.execute(
        "UPDATE campaigns SET start_date = ?, duration_days = ?, day_override = ? WHERE id = 1",
        (before["start_date"], before["duration_days"], before["day_override"]),
    )
    conn.commit()


def test_simulated_day_override_wins(conn, restore_campaign1):
    conn.execute("UPDATE campaigns SET day_override = 4 WHERE id = 1")
    conn.commit()
    assert get_campaign_day(conn, 1) == 4


def test_simulated_day_clamped_to_duration(conn, restore_campaign1):
    conn.execute("UPDATE campaigns SET day_override = 999 WHERE id = 1")
    conn.commit()
    assert get_campaign_day(conn, 1) == 7  # duration_days stays 7


def test_simulated_day_clamped_above_one(conn, restore_campaign1):
    conn.execute("UPDATE campaigns SET day_override = 0 WHERE id = 1")
    conn.commit()
    assert get_campaign_day(conn, 1) == 1


def test_live_clock_derives_from_start_date(conn, restore_campaign1):
    start = datetime.now() - timedelta(days=3)
    conn.execute(
        "UPDATE campaigns SET day_override = NULL, start_date = ?, duration_days = 14 WHERE id = 1",
        (start.strftime(ISO),),
    )
    conn.commit()
    # 3 full days elapsed since start -> day 4 (day 1 is the start day itself).
    assert get_campaign_day(conn, 1) == 4


def test_live_clock_clamped_to_duration_once_campaign_ends(conn, restore_campaign1):
    start = datetime.now() - timedelta(days=30)
    conn.execute(
        "UPDATE campaigns SET day_override = NULL, start_date = ?, duration_days = 7 WHERE id = 1",
        (start.strftime(ISO),),
    )
    conn.commit()
    assert get_campaign_day(conn, 1) == 7  # never reports a day beyond the campaign's own length


def test_live_clock_clamped_to_one_before_start(conn, restore_campaign1):
    start = datetime.now() + timedelta(days=5)  # a campaign that hasn't started yet
    conn.execute(
        "UPDATE campaigns SET day_override = NULL, start_date = ?, duration_days = 14 WHERE id = 1",
        (start.strftime(ISO),),
    )
    conn.commit()
    assert get_campaign_day(conn, 1) == 1


def test_unknown_campaign_raises(conn):
    with pytest.raises(ValueError):
        get_campaign_day(conn, 999999)
