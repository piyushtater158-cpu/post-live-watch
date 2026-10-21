"""Verifies app/db.py's guarded rebuild of post_snapshots: an existing DB built
against the OLD schema (reach/saves/shares NOT NULL, no source/fetched_at/
campaign columns) survives init_schema with every row intact, ends up with the
new nullable columns, and tolerates being run again. This is the one
non-additive migration in the app — everything else is a plain ALTER TABLE
ADD COLUMN — so it gets its own standalone DB rather than reusing the shared
seeded fixture in conftest.py.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db import init_schema

# The schema exactly as it shipped before this change: reach/saves/shares
# NOT NULL, and none of campaigns.day_override/status/metrics_provider/
# created_at, brands.ig_user_id, creators.ig_user_id, posts.ig_media_id/
# last_fetched_at, post_snapshots.source/fetched_at, or fetch_runs exist yet.
OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    product TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY,
    brand_id INTEGER NOT NULL REFERENCES brands(id),
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    required_disclosure TEXT NOT NULL,
    required_tag TEXT NOT NULL,
    required_hashtag TEXT NOT NULL,
    requires_link_sticker INTEGER NOT NULL DEFAULT 1,
    banned_claims TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    followers INTEGER NOT NULL,
    tier TEXT NOT NULL,
    niche TEXT NOT NULL,
    avg_reach REAL NOT NULL,
    avg_engagement_rate REAL NOT NULL,
    metrics_source TEXT
);
CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    creator_id INTEGER NOT NULL REFERENCES creators(id),
    format TEXT NOT NULL,
    fee REAL,
    promised_date TEXT NOT NULL,
    min_reach INTEGER,
    required_disclosure TEXT,
    required_tag TEXT,
    required_hashtag TEXT,
    requires_link_sticker INTEGER,
    deal_type TEXT NOT NULL DEFAULT 'paid',
    barter_value REAL,
    bonus_threshold INTEGER,
    bonus_amount REAL,
    waived_notes TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    deliverable_id INTEGER NOT NULL REFERENCES deliverables(id),
    posted_at TEXT,
    caption TEXT,
    original_caption TEXT,
    caption_edited_at TEXT,
    link_sticker_present INTEGER NOT NULL DEFAULT 0,
    permalink TEXT,
    is_story INTEGER NOT NULL DEFAULT 0,
    screenshot_uploaded INTEGER NOT NULL DEFAULT 0,
    deleted_at_day INTEGER,
    competitor_mentioned_day INTEGER
);
CREATE TABLE IF NOT EXISTS post_snapshots (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day_number INTEGER NOT NULL,
    reach INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    comments_count INTEGER NOT NULL,
    saves INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    still_live INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day_number INTEGER NOT NULL,
    author_handle TEXT NOT NULL,
    text TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    flag_id INTEGER,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    action TEXT NOT NULL,
    message_text TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_post ON post_snapshots(post_id, day_number);
"""


@pytest.fixture
def old_shape_db(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO brands (id, name, product) VALUES (1, 'GlowLeaf', 'serum')")
    conn.execute(
        "INSERT INTO campaigns (id, brand_id, name, start_date, duration_days, required_disclosure, "
        "required_tag, required_hashtag, requires_link_sticker, banned_claims) "
        "VALUES (1, 1, 'C', '2026-09-01T09:00:00', 7, '#ad', '@glowleaf', '#Glow', 1, '[]')"
    )
    conn.execute(
        "INSERT INTO creators (id, handle, followers, tier, niche, avg_reach, avg_engagement_rate) "
        "VALUES (1, 'oldcreator', 50000, 'micro', 'skincare', 16000, 0.05)"
    )
    conn.execute(
        "INSERT INTO deliverables (id, campaign_id, creator_id, format, fee, promised_date, min_reach) "
        "VALUES (1, 1, 1, 'reel', 10000, '2026-09-01T09:00:00', 9000)"
    )
    conn.execute(
        "INSERT INTO posts (id, deliverable_id, posted_at, link_sticker_present, is_story, screenshot_uploaded) "
        "VALUES (1, 1, NULL, 0, 0, 0)"
    )
    conn.execute(
        "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, still_live) "
        "VALUES (1, 1, 12000, 600, 40, 80, 20, 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def test_rebuild_preserves_existing_rows(old_shape_db):
    conn = old_shape_db
    before = dict(conn.execute("SELECT * FROM post_snapshots WHERE post_id = 1").fetchone())

    init_schema(conn)

    after = dict(conn.execute("SELECT * FROM post_snapshots WHERE post_id = 1").fetchone())
    for key in ("id", "post_id", "day_number", "reach", "likes", "comments_count", "saves", "shares", "still_live"):
        assert after[key] == before[key]


def test_rebuild_adds_nullable_columns(old_shape_db):
    conn = old_shape_db
    init_schema(conn)

    info = {row["name"]: row for row in conn.execute("PRAGMA table_info(post_snapshots)")}
    assert set(("source", "fetched_at")) <= set(info)
    assert info["reach"]["notnull"] == 0
    assert info["saves"]["notnull"] == 0
    assert info["shares"]["notnull"] == 0
    # likes/comments_count/still_live were never part of the problem — still required.
    assert info["likes"]["notnull"] == 1


def test_backfilled_source_defaults_to_seeded(old_shape_db):
    conn = old_shape_db
    init_schema(conn)
    row = conn.execute("SELECT source FROM post_snapshots WHERE post_id = 1").fetchone()
    assert row["source"] == "seeded"


def test_null_reach_insert_succeeds_after_rebuild(old_shape_db):
    conn = old_shape_db
    init_schema(conn)
    conn.execute(
        "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, "
        "still_live, source) VALUES (1, 2, NULL, 300, 10, NULL, NULL, 1, 'public')"
    )
    conn.commit()
    row = conn.execute("SELECT reach, saves, shares FROM post_snapshots WHERE day_number = 2").fetchone()
    assert row["reach"] is None and row["saves"] is None and row["shares"] is None


def test_index_survives_rebuild(old_shape_db):
    conn = old_shape_db
    init_schema(conn)
    idx_names = {row["name"] for row in conn.execute("PRAGMA index_list(post_snapshots)")}
    assert "idx_snapshots_post" in idx_names


def test_rebuild_is_idempotent(old_shape_db):
    conn = old_shape_db
    init_schema(conn)
    count_1 = conn.execute("SELECT COUNT(*) c FROM post_snapshots").fetchone()["c"]
    init_schema(conn)  # a second run must be a no-op, not an error or a duplicate
    count_2 = conn.execute("SELECT COUNT(*) c FROM post_snapshots").fetchone()["c"]
    assert count_1 == count_2 == 1


def test_additive_columns_also_backfilled(old_shape_db):
    """init_schema's existing _migrate_table path (unchanged by this plan) still
    adds every other new column — this is the regression guard for the parts of
    the migration that are NOT the risky rebuild."""
    conn = old_shape_db
    init_schema(conn)
    for table, column in [
        ("brands", "ig_user_id"),
        ("campaigns", "day_override"),
        ("campaigns", "status"),
        ("campaigns", "metrics_provider"),
        ("creators", "ig_user_id"),
        ("posts", "ig_media_id"),
        ("posts", "last_fetched_at"),
    ]:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert column in cols, f"{table}.{column} missing after migration"

    status = conn.execute("SELECT status, metrics_provider FROM campaigns WHERE id = 1").fetchone()
    assert status["status"] == "active"
    assert status["metrics_provider"] == "seeded"


def test_fetch_runs_table_created(old_shape_db):
    conn = old_shape_db
    init_schema(conn)
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "fetch_runs" in tables
