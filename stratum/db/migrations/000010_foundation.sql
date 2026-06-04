-- Stratum DB foundation 0.1 schema.
-- Explicit migration only. Do not auto-apply from connection.py while the
-- current working baseline is still active.

ALTER TABLE articles ADD COLUMN canonical_url TEXT;
ALTER TABLE articles ADD COLUMN source_domain TEXT;
ALTER TABLE articles ADD COLUMN locale TEXT;
ALTER TABLE articles ADD COLUMN run_date TEXT;
ALTER TABLE articles ADD COLUMN scale TEXT DEFAULT 'daily';
ALTER TABLE articles ADD COLUMN entity_ids TEXT;
ALTER TABLE articles ADD COLUMN term_ids TEXT;
ALTER TABLE articles ADD COLUMN content_hash TEXT;
ALTER TABLE articles ADD COLUMN artifact_path TEXT;

CREATE INDEX IF NOT EXISTS idx_articles_domain_run_date
    ON articles(domain, run_date);
CREATE INDEX IF NOT EXISTS idx_articles_domain_scale_run_date
    ON articles(domain, scale, run_date);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    domain TEXT,
    scale TEXT,
    period TEXT,
    run_date TEXT,
    status TEXT DEFAULT 'ok',
    version TEXT,
    runtime_mode TEXT,
    release_commit TEXT,
    markdown_path TEXT,
    html_path TEXT,
    pdf_path TEXT,
    run_manifest_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_domain_scale_period
    ON reports(domain, scale, period);

CREATE TABLE IF NOT EXISTS report_sections (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    section_key TEXT,
    title TEXT,
    position INTEGER,
    FOREIGN KEY(report_id) REFERENCES reports(id)
);

CREATE TABLE IF NOT EXISTS report_items (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    section_id TEXT,
    section_key TEXT,
    position INTEGER,
    title TEXT,
    body TEXT,
    signal_type TEXT,
    importance INTEGER,
    confidence TEXT,
    policy_decision TEXT,
    FOREIGN KEY(report_id) REFERENCES reports(id),
    FOREIGN KEY(section_id) REFERENCES report_sections(id)
);

CREATE TABLE IF NOT EXISTS report_item_events (
    report_item_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    link_type TEXT DEFAULT 'supports',
    confidence TEXT,
    PRIMARY KEY(report_item_id, event_id, link_type)
);

CREATE TABLE IF NOT EXISTS report_item_threads (
    report_item_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    link_type TEXT DEFAULT 'about',
    confidence TEXT,
    PRIMARY KEY(report_item_id, thread_id, link_type)
);

CREATE TABLE IF NOT EXISTS report_item_articles (
    report_item_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    role TEXT DEFAULT 'evidence',
    source_line TEXT,
    confidence TEXT,
    PRIMARY KEY(report_item_id, article_id, role)
);

CREATE TABLE IF NOT EXISTS event_articles (
    event_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    role TEXT DEFAULT 'evidence',
    confidence TEXT,
    PRIMARY KEY(event_id, article_id, role)
);

CREATE TABLE IF NOT EXISTS report_lineage (
    report_id TEXT NOT NULL,
    source_report_id TEXT,
    source_scale TEXT,
    source_period TEXT,
    source_event_id TEXT,
    source_thread_id TEXT,
    source_article_id TEXT,
    relation TEXT DEFAULT 'consumes'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_report_lineage_unique
    ON report_lineage (
        report_id,
        COALESCE(source_report_id, ''),
        COALESCE(source_event_id, ''),
        COALESCE(source_thread_id, ''),
        COALESCE(source_article_id, ''),
        COALESCE(relation, '')
    );

CREATE TABLE IF NOT EXISTS report_artifacts (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
