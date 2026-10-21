"""app/metrics/sync.py:sync_campaign — the write path that turns a
MetricsProvider's output into posts/post_snapshots rows, independent of
which provider produced it. Uses a FakeProvider (not InstagramProvider) so
these tests exercise sync's own matching/upsert/disappearance logic in
isolation from the HTTP layer, which tests/test_metrics_providers.py already
covers separately.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db import get_campaign_day
from app.metrics.base import MetricsProvider, PostMetrics
from app.metrics.sync import run_sync, sync_campaign

TABLES = ("fetch_runs", "decisions", "post_snapshots", "posts", "deliverables", "creators", "campaigns", "brands")


class FakeProvider(MetricsProvider):
    name = "fake"

    def __init__(self, media_by_creator: dict[str, list[PostMetrics]]):
        self._media = media_by_creator

    def fetch_creator_media(self, creator_ig_user_id, creator_handle):
        return self._media.get(creator_handle, [])


def _metrics(ig_media_id, reach, likes, comments, saves=None, shares=None, posted_at=None,
             caption=None, source="branded_content", still_live=True):
    return PostMetrics(
        ig_media_id=ig_media_id, reach=reach, likes=likes, comments_count=comments,
        saves=saves, shares=shares, still_live=still_live, caption=caption,
        posted_at=posted_at, permalink=f"https://instagram.com/p/{ig_media_id}/", source=source,
    )


@pytest.fixture
def synced_campaign(conn):
    """A fresh campaign + brand + creator + one reel deliverable/post, scoped
    to this test and cleaned up afterward — isolated from the shared seeded
    campaign 1 so sync's writes never touch its rows."""
    high = {t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"] for t in TABLES}
    start = datetime.now() - timedelta(days=2)

    brand_id = conn.execute("INSERT INTO brands (name, product) VALUES ('SyncBrand', 'Serum')").lastrowid
    campaign_id = conn.execute(
        "INSERT INTO campaigns (brand_id, name, start_date, duration_days, required_disclosure, required_tag, "
        "required_hashtag, requires_link_sticker, banned_claims, day_override, status, metrics_provider) "
        "VALUES (?, 'Sync Test', ?, 10, '#ad', '@b', '#h', 1, '[]', NULL, 'active', 'instagram')",
        (brand_id, start.isoformat()),
    ).lastrowid
    creator_id = conn.execute(
        "INSERT INTO creators (handle, followers, tier, niche, avg_reach, avg_engagement_rate, ig_user_id) "
        "VALUES ('synccreator', 50000, 'micro', 'skincare', 16000, 0.05, '17900000000000099')"
    ).lastrowid
    deliverable_id = conn.execute(
        "INSERT INTO deliverables (campaign_id, creator_id, format, fee, promised_date, min_reach) "
        "VALUES (?, ?, 'reel', 10000, ?, 15000)",
        (campaign_id, creator_id, start.isoformat()),
    ).lastrowid
    post_id = conn.execute(
        "INSERT INTO posts (deliverable_id, posted_at, link_sticker_present, is_story, screenshot_uploaded) "
        "VALUES (?, NULL, 0, 0, 0)", (deliverable_id,),
    ).lastrowid
    conn.commit()

    yield {"campaign_id": campaign_id, "creator_id": creator_id, "deliverable_id": deliverable_id,
           "post_id": post_id, "promised_date": start}

    for t in TABLES:
        conn.execute(f"DELETE FROM {t} WHERE id > ?", (high[t],))
    conn.commit()


def test_fresh_match_writes_snapshot_and_post_fields(conn, synced_campaign):
    cid, post_id = synced_campaign["campaign_id"], synced_campaign["post_id"]
    promised = synced_campaign["promised_date"]
    provider = FakeProvider({"synccreator": [
        _metrics("media_1", reach=40000, likes=2000, comments=120, saves=80, shares=10,
                 posted_at=promised.isoformat(), caption="original caption #ad"),
    ]})

    result = sync_campaign(conn, cid, provider)
    assert result["status"] == "ok"
    assert result["posts_updated"] == 1

    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    assert post["ig_media_id"] == "media_1"
    assert post["posted_at"] is not None
    assert post["original_caption"] == "original caption #ad"
    assert post["caption"] == "original caption #ad"

    day = get_campaign_day(conn, cid)
    snap = conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day),
    ).fetchone()
    assert snap["reach"] == 40000 and snap["likes"] == 2000 and snap["source"] == "branded_content"


def test_resync_updates_existing_snapshot_not_duplicates(conn, synced_campaign):
    cid, post_id = synced_campaign["campaign_id"], synced_campaign["post_id"]
    promised = synced_campaign["promised_date"]
    provider = FakeProvider({"synccreator": [
        _metrics("media_1", reach=40000, likes=2000, comments=120, posted_at=promised.isoformat()),
    ]})
    sync_campaign(conn, cid, provider)

    provider2 = FakeProvider({"synccreator": [
        _metrics("media_1", reach=45000, likes=2300, comments=140, posted_at=promised.isoformat()),
    ]})
    sync_campaign(conn, cid, provider2)

    day = get_campaign_day(conn, cid)
    rows = conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reach"] == 45000  # updated in place, not duplicated


def test_public_tier_snapshot_has_null_reach(conn, synced_campaign):
    cid, post_id = synced_campaign["campaign_id"], synced_campaign["post_id"]
    promised = synced_campaign["promised_date"]
    provider = FakeProvider({"synccreator": [
        _metrics("media_1", reach=None, likes=900, comments=40, posted_at=promised.isoformat(), source="public"),
    ]})
    sync_campaign(conn, cid, provider)

    day = get_campaign_day(conn, cid)
    snap = conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day),
    ).fetchone()
    assert snap["reach"] is None
    assert snap["source"] == "public"

    # And the rules engine respects it — rule 5/12 silent, data_notes explains why.
    from app.rules.engine import evaluate_post
    result = evaluate_post(conn, post_id, current_day=day)
    assert 5 not in {f["rule_id"] for f in result["flags"]}
    assert result["data_notes"] and result["data_notes"][0]["type"] == "reach_unavailable"


def test_caption_change_sets_edited_at(conn, synced_campaign):
    cid, post_id = synced_campaign["campaign_id"], synced_campaign["post_id"]
    promised = synced_campaign["promised_date"]
    sync_campaign(conn, cid, FakeProvider({"synccreator": [
        _metrics("media_1", reach=40000, likes=2000, comments=120, posted_at=promised.isoformat(),
                 caption="original"),
    ]}))
    sync_campaign(conn, cid, FakeProvider({"synccreator": [
        _metrics("media_1", reach=41000, likes=2050, comments=125, posted_at=promised.isoformat(),
                 caption="edited caption with a banned claim"),
    ]}))
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    assert post["original_caption"] == "original"  # preserved
    assert post["caption"] == "edited caption with a banned claim"
    assert post["caption_edited_at"] is not None


def test_disappeared_media_marks_still_live_false(conn, synced_campaign):
    cid, post_id = synced_campaign["campaign_id"], synced_campaign["post_id"]
    promised = synced_campaign["promised_date"]
    sync_campaign(conn, cid, FakeProvider({"synccreator": [
        _metrics("media_1", reach=40000, likes=2000, comments=120, posted_at=promised.isoformat()),
    ]}))
    # Second sync: the creator's media list no longer includes media_1 at all (deleted).
    sync_campaign(conn, cid, FakeProvider({"synccreator": []}))

    day = get_campaign_day(conn, cid)
    snap = conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day),
    ).fetchone()
    assert snap["still_live"] == 0
    assert snap["reach"] == 40000  # last known number carried forward, not invented


def test_unmatched_media_recorded_not_guessed(conn, synced_campaign):
    cid = synced_campaign["campaign_id"]
    # A media item with a posted_at far outside this deliverable's promised window,
    # alongside the real match — the far-off one still gets matched (nearest-time,
    # no threshold) UNLESS there's no remaining deliverable to absorb it. Use two
    # items against one deliverable to force a genuine leftover.
    promised = synced_campaign["promised_date"]
    far = promised + timedelta(days=365)
    provider = FakeProvider({"synccreator": [
        _metrics("media_1", reach=40000, likes=2000, comments=120, posted_at=promised.isoformat()),
        _metrics("media_2", reach=10000, likes=500, comments=20, posted_at=far.isoformat()),
    ]})
    result = sync_campaign(conn, cid, provider)
    assert result["posts_updated"] == 1
    assert any(e.get("ig_media_id") == "media_2" for e in result["errors"])


def test_missing_creator_ig_user_id_resolved_and_cached(conn, synced_campaign):
    cid, creator_id = synced_campaign["campaign_id"], synced_campaign["creator_id"]
    conn.execute("UPDATE creators SET ig_user_id = NULL WHERE id = ?", (creator_id,))
    conn.commit()
    seen_ids = []

    class ResolvingProvider(FakeProvider):
        def resolve_ig_user_id(self, handle):
            return "17900000000000555" if handle == "synccreator" else None

        def fetch_creator_media(self, creator_ig_user_id, creator_handle):
            seen_ids.append(creator_ig_user_id)
            return []

    sync_campaign(conn, cid, ResolvingProvider({}))
    assert seen_ids == ["17900000000000555"]  # branded-content tier gets the id on this same run
    row = conn.execute("SELECT ig_user_id FROM creators WHERE id = ?", (creator_id,)).fetchone()
    assert row["ig_user_id"] == "17900000000000555"


def test_fetch_run_recorded(conn, synced_campaign):
    cid = synced_campaign["campaign_id"]
    sync_campaign(conn, cid, FakeProvider({}))
    run = conn.execute(
        "SELECT * FROM fetch_runs WHERE campaign_id = ? ORDER BY id DESC LIMIT 1", (cid,)
    ).fetchone()
    assert run is not None
    assert run["provider"] == "fake"


def test_run_sync_not_configured_without_env(conn, synced_campaign, monkeypatch):
    monkeypatch.delenv("META_BUSINESS_ID", raising=False)
    monkeypatch.delenv("META_IG_BUSINESS_ID", raising=False)
    monkeypatch.delenv("META_SYSTEM_USER_TOKEN", raising=False)
    result = run_sync(conn, synced_campaign["campaign_id"])
    assert result["status"] == "not_configured"


def test_run_sync_not_applicable_for_seeded_campaign(conn):
    result = run_sync(conn, 1)  # the seeded demo campaign
    assert result["status"] == "not_applicable"
