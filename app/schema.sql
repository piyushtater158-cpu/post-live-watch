-- Post-Live Watch schema. SQLite. All data is SAMPLE DATA (synthetic).

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    product TEXT NOT NULL,
    ig_user_id TEXT                 -- the brand's own IG Professional account id; set once the
                                     -- Meta connector is configured (app/metrics/instagram.py)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY,
    brand_id INTEGER NOT NULL REFERENCES brands(id),
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,       -- ISO datetime, day 1 00:00
    duration_days INTEGER NOT NULL,
    required_disclosure TEXT NOT NULL,  -- '|'-separated accepted tokens, e.g. '#ad|paid partnership'
    required_tag TEXT NOT NULL,
    required_hashtag TEXT NOT NULL,
    requires_link_sticker INTEGER NOT NULL DEFAULT 1,  -- campaign default; deliverables.requires_link_sticker overrides per-deal
    banned_claims TEXT NOT NULL,     -- JSON list of strings
    day_override INTEGER,           -- NULL = live clock, derived from start_date (app/db.py:get_campaign_day);
                                     -- set = simulated clock (the day simulator moves this)
    status TEXT NOT NULL DEFAULT 'active',          -- 'active' | 'completed' | 'archived'
    metrics_provider TEXT NOT NULL DEFAULT 'seeded', -- 'seeded' | 'manual' | 'instagram' (app/metrics/)
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    followers INTEGER NOT NULL,
    tier TEXT NOT NULL,              -- 'mid' | 'micro'
    niche TEXT NOT NULL,
    avg_reach REAL NOT NULL,
    avg_engagement_rate REAL NOT NULL,
    metrics_source TEXT,             -- NULL = seeded/measured; 'estimated' = app/intake.py's
                                      -- follower-count estimate, never AI-invented; 'am_entered' =
                                      -- an AM typed a real number over the estimate at intake;
                                      -- 'measured' = app/metrics/instagram.py's resolve_creator pull.
    ig_user_id TEXT                  -- resolved once via resolve_creator, cached rather than
                                      -- re-looked-up by handle on every sync.
);

CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    creator_id INTEGER NOT NULL REFERENCES creators(id),
    format TEXT NOT NULL,            -- 'reel' | 'carousel' | 'story'
    fee REAL,                        -- NULL for barter/affiliate deals with no cash fee
    promised_date TEXT NOT NULL,     -- ISO datetime due date
    min_reach INTEGER,               -- NULL = no reach guarantee negotiated (e.g. barter)

    -- Per-deliverable overrides on the campaign brief. NULL = inherit the
    -- campaign default; '' (empty string) on required_tag/required_hashtag
    -- means that requirement was negotiated away entirely. Resolved by
    -- app/rules/contract.py:resolve_terms, never read directly by a detector.
    required_disclosure TEXT,        -- override; '|'-separated accepted tokens
    required_tag TEXT,               -- override; '' = waived
    required_hashtag TEXT,           -- override; '' = waived
    requires_link_sticker INTEGER,   -- override; NULL = infer from format (stories only)

    deal_type TEXT NOT NULL DEFAULT 'paid',  -- 'paid' | 'barter' | 'affiliate' | 'paid_plus_bonus'
    barter_value REAL,               -- rupee-equivalent of product given (deal_type='barter')
    bonus_threshold INTEGER,         -- reach threshold that unlocks the bonus (deal_type='paid_plus_bonus')
    bonus_amount REAL,               -- bonus amount paid if bonus_threshold is met

    waived_notes TEXT                -- JSON {requirement: human reason}, e.g. {"required_hashtag": "negotiated out — exclusive deal with a rival brand"}
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    deliverable_id INTEGER NOT NULL REFERENCES deliverables(id),
    posted_at TEXT,                  -- ISO datetime, NULL if not yet posted
    caption TEXT,
    original_caption TEXT,           -- as first approved; used to detect post-approval edits
    caption_edited_at TEXT,
    link_sticker_present INTEGER NOT NULL DEFAULT 0,
    permalink TEXT,
    is_story INTEGER NOT NULL DEFAULT 0,  -- DEPRECATED: duplicates deliverables.format == 'story'.
                                           -- Kept for the persisted volume's sake; nothing reads it
                                           -- anymore — app/rules/contract.py derives is_story from format.
    screenshot_uploaded INTEGER NOT NULL DEFAULT 0,
    deleted_at_day INTEGER,          -- day number it was first found missing; NULL if never deleted
    competitor_mentioned_day INTEGER, -- day number creator posted a competitor mention; NULL if none
    ig_media_id TEXT,                -- Instagram media id; the join key app/metrics/sync.py matches
                                      -- fetched posts against. NULL until the first successful fetch.
    last_fetched_at TEXT              -- ISO datetime of the last successful metrics sync for this post
);

-- reach/saves/shares are nullable: the public (business_discovery) metrics tier
-- returns likes and comments only, never reach — and 0 is not a safe stand-in
-- (it would make rule_5 fire falsely and rule_12 never fire; see
-- app/intake.py's identical reasoning for avg_reach). NULL means "not known from
-- this source", read by app/rules/detectors.py as "this rule cannot run".
-- NOTE: a pre-existing DB has these NOT NULL and is rebuilt by
-- app/db.py's _TABLE_REBUILDS, not by this guarded CREATE.
CREATE TABLE IF NOT EXISTS post_snapshots (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day_number INTEGER NOT NULL,     -- 1..duration_days
    reach INTEGER,
    likes INTEGER NOT NULL,
    comments_count INTEGER NOT NULL,
    saves INTEGER,
    shares INTEGER,
    still_live INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'seeded',  -- 'seeded' | 'branded_content' | 'public' | 'am_entered'
    fetched_at TEXT                          -- ISO datetime this row was fetched/entered, NULL for seeded rows
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day_number INTEGER NOT NULL,
    author_handle TEXT NOT NULL,
    text TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en'  -- 'en' | 'hi-en' (hinglish)
);

CREATE TABLE IF NOT EXISTS historical_campaigns (
    id INTEGER PRIMARY KEY,
    creator_id INTEGER NOT NULL REFERENCES creators(id),
    campaign_name TEXT NOT NULL,
    month TEXT NOT NULL,                 -- 'YYYY-MM'
    delivered_on_time INTEGER NOT NULL,
    performance_ratio REAL NOT NULL,     -- actual reach / promised min_reach
    flags_count INTEGER NOT NULL DEFAULT 0,
    fix_speed_days REAL,                 -- NULL if no flags that campaign
    competitor_conflict INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL                -- 'completed' | 'dropped' | 'escalated'
);

CREATE TABLE IF NOT EXISTS flags (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    rule_id INTEGER NOT NULL,        -- 1..12
    rule_name TEXT NOT NULL,
    severity INTEGER NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,          -- JSON blob of supporting data
    detected_day INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    flag_id INTEGER REFERENCES flags(id),
    post_id INTEGER NOT NULL REFERENCES posts(id),
    action TEXT NOT NULL,             -- 'approve' | 'edit' | 'dismiss'
    message_text TEXT,
    created_at TEXT NOT NULL,
    source TEXT                       -- NULL/'flag' = acted on a flag (existing); 'intake' = this
                                       -- row is an audit record of a deal-intake confirmation,
                                       -- message_text holds the raw brief text
);

-- One row per metrics sync attempt (app/metrics/sync.py:sync_campaign), success or failure —
-- the audit trail for "did the connector actually run, and what happened."
CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    provider TEXT NOT NULL,          -- 'instagram' | 'manual' | 'seeded'
    started_at TEXT NOT NULL,
    finished_at TEXT,
    posts_attempted INTEGER NOT NULL DEFAULT 0,
    posts_updated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,             -- 'ok' | 'partial' | 'not_configured' | 'error'
    errors TEXT                       -- JSON list of {post_id|creator_handle, message}
);

CREATE INDEX IF NOT EXISTS idx_snapshots_post ON post_snapshots(post_id, day_number);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, day_number);
CREATE INDEX IF NOT EXISTS idx_deliverables_campaign ON deliverables(campaign_id);
CREATE INDEX IF NOT EXISTS idx_deliverables_creator ON deliverables(campaign_id, creator_id);
CREATE INDEX IF NOT EXISTS idx_historical_creator ON historical_campaigns(creator_id);
CREATE INDEX IF NOT EXISTS idx_flags_post ON flags(post_id);
CREATE INDEX IF NOT EXISTS idx_fetch_runs_campaign ON fetch_runs(campaign_id, started_at);
