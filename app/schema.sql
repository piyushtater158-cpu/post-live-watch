-- Post-Live Watch schema. SQLite. All data is SAMPLE DATA (synthetic).

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
    start_date TEXT NOT NULL,       -- ISO datetime, day 1 00:00
    duration_days INTEGER NOT NULL,
    required_disclosure TEXT NOT NULL,
    required_tag TEXT NOT NULL,
    required_hashtag TEXT NOT NULL,
    requires_link_sticker INTEGER NOT NULL DEFAULT 1,
    banned_claims TEXT NOT NULL     -- JSON list of strings
);

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    followers INTEGER NOT NULL,
    tier TEXT NOT NULL,              -- 'mid' | 'micro'
    niche TEXT NOT NULL,
    avg_reach REAL NOT NULL,
    avg_engagement_rate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    creator_id INTEGER NOT NULL REFERENCES creators(id),
    format TEXT NOT NULL,            -- 'reel' | 'carousel' | 'story'
    fee REAL NOT NULL,
    promised_date TEXT NOT NULL,     -- ISO datetime due date
    min_reach INTEGER NOT NULL
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
    is_story INTEGER NOT NULL DEFAULT 0,
    screenshot_uploaded INTEGER NOT NULL DEFAULT 0,
    deleted_at_day INTEGER,          -- day number it was first found missing; NULL if never deleted
    competitor_mentioned_day INTEGER -- day number creator posted a competitor mention; NULL if none
);

CREATE TABLE IF NOT EXISTS post_snapshots (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    day_number INTEGER NOT NULL,     -- 1..duration_days
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
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_post ON post_snapshots(post_id, day_number);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, day_number);
CREATE INDEX IF NOT EXISTS idx_deliverables_campaign ON deliverables(campaign_id);
CREATE INDEX IF NOT EXISTS idx_historical_creator ON historical_campaigns(creator_id);
CREATE INDEX IF NOT EXISTS idx_flags_post ON flags(post_id);
