-- ============================================================
-- Stratum Database Schema
-- Single SQLite file per domain: {WORKSPACE}/data/{domain}/{domain}.db
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- Articles (pipeline artifacts, for FK integrity)
-- ============================================================
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    title TEXT,
    url TEXT,
    source TEXT,
    published_at TEXT,
    snippet TEXT,
    domain TEXT NOT NULL
);

-- ============================================================
-- Sources
-- ============================================================
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    type TEXT NOT NULL,                -- MEDIA/NEWSROOM/BLOG/ANALYST/SOCIAL
    url TEXT,
    locale TEXT,
    reliability REAL DEFAULT 0.5,
    status TEXT DEFAULT 'trial',       -- active/trial/deprecated/blocked
    added_by TEXT DEFAULT 'seed',      -- seed/source_registry/agent
    first_seen TEXT,
    last_seen TEXT,
    tags TEXT                          -- JSON array
);

CREATE TABLE IF NOT EXISTS source_profiles (
    source_id TEXT PRIMARY KEY REFERENCES sources(id),
    avg_latency_hours REAL,
    hit_rate_7d REAL,
    hit_rate_30d REAL,
    hit_rate_90d REAL,
    exclusive_rate REAL,
    coverage_breadth TEXT,             -- JSON array
    structural_sensitivity REAL,
    evaluated_at TEXT
);

-- ============================================================
-- Queries
-- ============================================================
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    locale TEXT NOT NULL,
    intent TEXT NOT NULL,              -- detection/confirmation/verification/context/structural
    dimension TEXT DEFAULT 'general',  -- briefing coverage dimension
    include_domains TEXT,              -- JSON array of engine include-domain filters
    thread_id TEXT,                    -- NULL = standalone
    keyword_ids TEXT,                  -- JSON array of keyword IDs
    status TEXT DEFAULT 'active',      -- active/stale/deprecated
    created_at TEXT,
    last_run TEXT,
    hit_count_7d INTEGER DEFAULT 0,
    hit_count_30d INTEGER DEFAULT 0,
    avg_articles REAL DEFAULT 0,
    signal_score REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS query_run_stats (
    query_id TEXT NOT NULL REFERENCES queries(id),
    run_date TEXT NOT NULL,
    results_count INTEGER DEFAULT 0,
    status TEXT,
    updated_at TEXT,
    PRIMARY KEY (query_id, run_date)
);

CREATE TABLE IF NOT EXISTS search_engine_health (
    engine TEXT NOT NULL,
    run_date TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    successes INTEGER DEFAULT 0,
    no_results INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    rate_limited INTEGER DEFAULT 0,
    not_configured INTEGER DEFAULT 0,
    unsupported INTEGER DEFAULT 0,
    health_score REAL DEFAULT 0,
    failure_rate REAL DEFAULT 0,
    recommendation TEXT,
    errors TEXT,
    updated_at TEXT,
    PRIMARY KEY (engine, run_date)
);

-- ============================================================
-- Keywords (atomic search units)
-- ============================================================
CREATE TABLE IF NOT EXISTS keywords (
    id TEXT PRIMARY KEY,               -- kw-samsung, kw-hbm4, kw-high-capacity
    text TEXT NOT NULL,
    locale TEXT NOT NULL,
    type TEXT NOT NULL,                -- COMPANY/TECHNOLOGY/PRODUCT/ATTRIBUTE
    entity_id TEXT,                    -- FK to entities (nullable)
    term_id TEXT,                      -- FK to terms (nullable)
    is_core INTEGER DEFAULT 0,
    frequency_7d INTEGER DEFAULT 0,
    frequency_30d INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT,
    source TEXT DEFAULT 'domain.yaml'  -- domain.yaml/normalize/agent
);

-- ============================================================
-- Keyword-Article association
-- ============================================================
CREATE TABLE IF NOT EXISTS keyword_article (
    article_id TEXT NOT NULL,
    keyword_id TEXT NOT NULL REFERENCES keywords(id),
    source TEXT NOT NULL,              -- title/snippet
    PRIMARY KEY (article_id, keyword_id)
);

-- ============================================================
-- Keyword-Event association
-- ============================================================
CREATE TABLE IF NOT EXISTS keyword_event (
    event_id TEXT NOT NULL,
    keyword_id TEXT NOT NULL REFERENCES keywords(id),
    weight INTEGER DEFAULT 1,
    PRIMARY KEY (event_id, keyword_id)
);

-- ============================================================
-- Entities (companies, technologies, products, standards)
-- ============================================================
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,                -- COMPANY/TECHNOLOGY/PRODUCT/STANDARD
    name_en TEXT,
    name_zh TEXT,
    aliases TEXT,                      -- JSON array
    status TEXT DEFAULT 'emerging',    -- emerging/active/dominant/cooling/deprecated
    importance REAL DEFAULT 0.5,
    first_seen TEXT,
    last_seen TEXT,
    article_count_7d INTEGER DEFAULT 0,
    article_count_30d INTEGER DEFAULT 0,
    active_thread_ids TEXT             -- JSON array
);

-- ============================================================
-- Terms
-- ============================================================
CREATE TABLE IF NOT EXISTS terms (
    id TEXT PRIMARY KEY,
    type TEXT,
    name_en TEXT,
    name_zh TEXT,
    aliases TEXT,
    parent_id TEXT REFERENCES terms(id),
    frequency_7d INTEGER DEFAULT 0,
    frequency_30d INTEGER DEFAULT 0,
    trend TEXT DEFAULT 'stable',       -- rising/stable/declining/emerging
    first_seen TEXT,
    last_seen TEXT
);

-- ============================================================
-- Threads (cross-day tracking containers)
-- ============================================================
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,               -- et-2026-001
    label TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'emerging',    -- emerging/active/cooling/dormant/resolved
    priority INTEGER DEFAULT 3,
    first_event_date TEXT,
    last_event_date TEXT,
    event_count_daily INTEGER DEFAULT 0,
    event_count_weekly INTEGER DEFAULT 0,
    parent_thread_id TEXT REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS thread_entities (
    thread_id TEXT REFERENCES threads(id),
    entity_id TEXT REFERENCES entities(id),
    role TEXT DEFAULT 'subject',       -- subject/affected/mentioned
    PRIMARY KEY (thread_id, entity_id)
);

-- ============================================================
-- Events (nodes in a thread, one per scale per period)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,               -- ev-2026-05-30-001
    thread_id TEXT NOT NULL REFERENCES threads(id),
    scale TEXT NOT NULL,               -- daily/weekly/monthly/quarterly/yearly
    date TEXT NOT NULL,
    title TEXT,
    article_ids TEXT,                  -- JSON array
    entity_ids TEXT,                   -- JSON array
    term_ids TEXT,                     -- JSON array
    source_domains TEXT,               -- JSON array
    confidence TEXT DEFAULT 'B',
    briefing_id TEXT,
    created_at TEXT,
    status TEXT DEFAULT 'emerging',     -- emerging/active/cooling/resolved/archived
    priority INTEGER DEFAULT 3          -- 1 (highest) - 5 (lowest)
);

-- ============================================================
-- Causal Edges
-- ============================================================
CREATE TABLE IF NOT EXISTS causal_edges (
    id TEXT PRIMARY KEY,
    cause_thread_id TEXT NOT NULL REFERENCES threads(id),
    effect_thread_id TEXT NOT NULL REFERENCES threads(id),
    mechanism TEXT NOT NULL,
    confidence TEXT DEFAULT 'B',
    scale TEXT NOT NULL,               -- daily/quarterly
    source_briefing TEXT,
    verified INTEGER,                  -- NULL=pending, 0=false, 1=true
    verified_at TEXT,
    verified_by_scale TEXT,
    created_at TEXT
);

-- ============================================================
-- Judgments (testable hypotheses)
-- ============================================================
CREATE TABLE IF NOT EXISTS judgments (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,         -- entity/event_pair
    target_entity_ids TEXT,            -- JSON array
    target_thread_ids TEXT,            -- JSON array
    hypothesis TEXT NOT NULL,
    confidence TEXT DEFAULT 'B',
    expected_verification TEXT,
    scale TEXT NOT NULL,               -- daily/weekly/quarterly/yearly
    source_briefing TEXT,
    result TEXT,                       -- NULL/pending/correct/incorrect/partially_correct
    verified_at TEXT,
    verified_by_scale TEXT,
    actual_outcome TEXT,
    created_at TEXT
);

-- ============================================================
-- Entity Snapshots (periodic per-scale summaries)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_snapshots (
    entity_id TEXT REFERENCES entities(id),
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    status TEXT,
    key_events TEXT,                   -- JSON array
    article_count INTEGER,
    thread_ids TEXT,                   -- JSON array
    importance_delta REAL,
    summary TEXT,
    PRIMARY KEY (entity_id, scale, period)
);

-- ============================================================
-- Coverage (per-period coverage reports)
-- ============================================================
CREATE TABLE IF NOT EXISTS coverage (
    id TEXT PRIMARY KEY,
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    covered_threads TEXT,              -- JSON array
    missed_threads TEXT,
    stale_entities TEXT,
    missed_dimensions TEXT,
    source_contribution TEXT           -- JSON {source: article_count}
);

-- ============================================================
-- Cascade Logs
-- ============================================================
CREATE TABLE IF NOT EXISTS cascade_logs (
    id TEXT PRIMARY KEY,
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    run_at TEXT,
    consumed_from TEXT,
    consumed_window TEXT,
    consumed_causal_edges INTEGER DEFAULT 0,
    consumed_judgments INTEGER DEFAULT 0,
    fresh_search_articles INTEGER DEFAULT 0,
    produced_judgments INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok'           -- ok/partial/failed
);
