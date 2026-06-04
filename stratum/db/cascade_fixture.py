"""Replayable cascade fixture for database development and validation.

The fixture behaves like a small historical world. It first persists daily
articles, events, judgments, and reports into one SQLite database. Weekly,
monthly, quarterly, and yearly reports are then generated from that same
database through the DB-native synthesis runtime, so every higher scale consumes
the lower-scale outputs that were already persisted before it ran.

This module is for tests and development diagnostics only. It is not used by
the production daily pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from stratum.db.connection import get_db
from stratum.db.migration import apply_foundation_migration
from stratum.db.persistence import link_event_articles, upsert_articles, upsert_report_bundle
from stratum.db.service import (
    get_cascade_inputs,
    get_judgment_status,
    get_key_events,
    get_key_timeline,
    get_report_context,
    get_report_item_evidence,
    get_technology_progress,
    get_trend_summary,
    trace_report_lineage,
)
from stratum.db.synthesis import synthesize_cascade_report


CASCADE_PERIODS = (
    ("weekly", "2026-W22"),
    ("monthly", "2026-05"),
    ("quarterly", "2026-Q2"),
    ("yearly", "2026"),
)


DAILY_STORIES = [
    {
        "day": "2026-05-25",
        "event_id": "ev-2026-05-25-hbm",
        "thread_id": "et-hbm-race",
        "article_id": "a-20260525-hbm",
        "title": "Samsung starts HBM4 qualification window",
        "entities": ["samsung"],
        "terms": ["hbm"],
        "priority": 1,
    },
    {
        "day": "2026-05-27",
        "event_id": "ev-2026-05-27-hbm",
        "thread_id": "et-hbm-race",
        "article_id": "a-20260527-hbm",
        "title": "SK hynix expands HBM capacity",
        "entities": ["sk-hynix"],
        "terms": ["hbm"],
        "priority": 1,
    },
    {
        "day": "2026-05-29",
        "event_id": "ev-2026-05-29-nand",
        "thread_id": "et-nand-pricing",
        "article_id": "a-20260529-nand",
        "title": "NAND contract prices rise",
        "entities": ["samsung", "micron"],
        "terms": ["nand"],
        "priority": 2,
    },
    {
        "day": "2026-05-31",
        "event_id": "ev-2026-05-31-hbm",
        "thread_id": "et-hbm-race",
        "article_id": "a-20260531-hbm",
        "title": "Micron narrows HBM gap",
        "entities": ["micron"],
        "terms": ["hbm"],
        "priority": 2,
    },
]


def build_constructed_cascade(domain: str = "storage") -> dict[str, Any]:
    """Build a deterministic daily-to-yearly cascade fixture in one test DB."""
    conn = get_db(domain)
    apply_foundation_migration(conn)
    _seed_event_store(conn)
    conn.close()

    _persist_daily_history(domain)
    _persist_same_scale_fresh_evidence(domain)
    synthesis_runs = _run_scale_cascade(domain)
    return analyze_constructed_cascade(domain, synthesis_runs=synthesis_runs)


def analyze_constructed_cascade(
    domain: str = "storage",
    *,
    synthesis_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a compact analysis snapshot from the constructed fixture."""
    return {
        "synthesis_runs": synthesis_runs or [],
        "weekly_inputs": get_cascade_inputs(domain, "weekly", "2026-W22"),
        "monthly_inputs": get_cascade_inputs(domain, "monthly", "2026-05"),
        "quarterly_inputs": get_cascade_inputs(domain, "quarterly", "2026-Q2"),
        "yearly_inputs": get_cascade_inputs(domain, "yearly", "2026"),
        "yearly_context": get_report_context(domain, "yearly", "2026"),
        "daily_trend": get_trend_summary(domain, "daily", "2026-05-25", "2026-05-31"),
        "judgment_status": get_judgment_status(domain, start_period="2026-05-25", end_period="2026-05-31"),
        "key_events": get_key_events(domain, "daily", "2026-05-25", "2026-05-31", limit=5),
        "key_timeline": get_key_timeline(domain, "daily", "2026-05-25", "2026-05-31"),
        "technology_progress": get_technology_progress(
            domain,
            "hbm",
            entity_ids=["samsung", "sk-hynix", "micron"],
        ),
        "weekly_item_evidence": get_report_item_evidence(
            domain,
            f"report-{domain}-weekly-2026-W22-trend-1",
        ),
        "yearly_lineage": trace_report_lineage(domain, f"report-{domain}-yearly-2026"),
    }


def _seed_event_store(conn) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO entities (id, type, name_en, status)
        VALUES (?, 'COMPANY', ?, 'active')
        """,
        [
            ("samsung", "Samsung"),
            ("sk-hynix", "SK hynix"),
            ("micron", "Micron"),
        ],
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO terms (id, type, name_en, trend)
        VALUES (?, 'TECHNOLOGY', ?, 'rising')
        """,
        [
            ("hbm", "HBM"),
            ("nand", "NAND"),
        ],
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO threads (
            id, label, description, status, priority, first_event_date,
            last_event_date, event_count_daily, event_count_weekly
        )
        VALUES (?, ?, '', 'active', ?, ?, ?, ?, 0)
        """,
        [
            ("et-hbm-race", "HBM qualification race", 1, "2026-05-25", "2026-05-31", 3),
            ("et-nand-pricing", "NAND pricing cycle", 2, "2026-05-29", "2026-05-29", 1),
        ],
    )

    for story in DAILY_STORIES:
        conn.execute(
            """
            INSERT OR REPLACE INTO events (
                id, thread_id, scale, date, title, article_ids, entity_ids,
                term_ids, source_domains, confidence, briefing_id, created_at,
                status, priority
            )
            VALUES (?, ?, 'daily', ?, ?, ?, ?, ?, '["example.com"]', 'B', ?, ?, 'active', ?)
            """,
            (
                story["event_id"],
                story["thread_id"],
                story["day"],
                story["title"],
                json.dumps([story["article_id"]]),
                json.dumps(story["entities"]),
                json.dumps(story["terms"]),
                f"daily-{story['day']}",
                f"{story['day']}T08:00:00+08:00",
                story["priority"],
            ),
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO judgments (
            id, target_type, target_entity_ids, target_thread_ids, hypothesis,
            confidence, expected_verification, scale, source_briefing, result,
            created_at
        )
        VALUES (?, 'entity', ?, ?, ?, 'B', ?, ?, ?, ?, ?)
        """,
        [
            (
                "jd-daily-hbm",
                json.dumps(["samsung"]),
                json.dumps(["et-hbm-race"]),
                "Samsung remains in the HBM qualification window",
                "weekly check",
                "daily",
                "daily-2026-05-31",
                "supported",
                "2026-05-31T08:00:00+08:00",
            ),
            (
                "jd-weekly-hbm",
                json.dumps(["samsung", "sk-hynix", "micron"]),
                json.dumps(["et-hbm-race"]),
                "HBM competition will remain the top memory driver in June",
                "monthly check",
                "weekly",
                "weekly-2026-W22",
                None,
                "2026-05-31T08:00:00+08:00",
            ),
        ],
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO causal_edges (
            id, cause_thread_id, effect_thread_id, mechanism, confidence,
            scale, source_briefing, verified, created_at
        )
        VALUES (
            'ce-daily-hbm-nand', 'et-hbm-race', 'et-nand-pricing',
            'HBM capacity allocation tightens conventional memory supply',
            'B', 'daily', 'daily-2026-05-31', NULL, '2026-05-31T08:00:00+08:00'
        )
        """
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO entity_snapshots (
            entity_id, scale, period, status, key_events, article_count,
            thread_ids, importance_delta, summary
        )
        VALUES (?, 'daily', ?, 'active', ?, ?, ?, ?, ?)
        """,
        [
            ("samsung", "2026-05-31", json.dumps(["Samsung starts HBM4 qualification window"]), 1, json.dumps(["et-hbm-race"]), 0.2, ""),
            ("sk-hynix", "2026-05-31", json.dumps(["SK hynix expands HBM capacity"]), 1, json.dumps(["et-hbm-race"]), 0.1, ""),
            ("micron", "2026-05-31", json.dumps(["Micron narrows HBM gap"]), 1, json.dumps(["et-hbm-race"]), 0.3, ""),
        ],
    )
    conn.commit()


def _persist_daily_history(domain: str) -> None:
    articles = [
        {
            "id": "a-20260525-hbm",
            "title": "Samsung HBM4 qualification",
            "url": "https://example.com/samsung-hbm",
            "source": "Example",
            "published_at": "2026-05-25",
            "locale": "en",
            "entity_ids": ["samsung"],
            "term_ids": ["hbm"],
            "snippet": "Samsung qualification starts.",
        },
        {
            "id": "a-20260527-hbm",
            "title": "SK hynix HBM capacity",
            "url": "https://example.com/sk-hynix-hbm",
            "source": "Example",
            "published_at": "2026-05-27",
            "locale": "en",
            "entity_ids": ["sk-hynix"],
            "term_ids": ["hbm"],
            "snippet": "Capacity expands.",
        },
        {
            "id": "a-20260529-nand",
            "title": "NAND prices rise",
            "url": "https://example.com/nand",
            "source": "Example",
            "published_at": "2026-05-29",
            "locale": "en",
            "entity_ids": ["samsung", "micron"],
            "term_ids": ["nand"],
            "snippet": "NAND prices rise.",
        },
        {
            "id": "a-20260531-hbm",
            "title": "Micron narrows HBM gap",
            "url": "https://example.com/micron-hbm",
            "source": "Example",
            "published_at": "2026-05-31",
            "locale": "en",
            "entity_ids": ["micron"],
            "term_ids": ["hbm"],
            "snippet": "Micron narrows gap.",
        },
    ]
    upsert_articles(domain, articles, "2026-05-31", artifact_path="/tmp/articles.jsonl")
    link_event_articles(
        domain,
        [
            {"event_id": story["event_id"], "article_id": story["article_id"]}
            for story in DAILY_STORIES
        ],
    )

    for story in DAILY_STORIES:
        report_id = f"report-{domain}-daily-{story['day']}"
        item_id = f"item-{story['day']}"
        upsert_report_bundle(
            domain,
            {
                "id": report_id,
                "scale": "daily",
                "period": story["day"],
                "run_date": story["day"],
                "markdown_path": f"/tmp/{story['day']}.md",
            },
            sections=[{"section_key": "today", "title": "Today", "position": 1}],
            items=[
                {
                    "id": item_id,
                    "section_key": "today",
                    "position": 1,
                    "title": story["title"],
                    "body": story["title"],
                    "signal_type": "main",
                    "importance": story["priority"],
                }
            ],
            item_events=[{"report_item_id": item_id, "event_id": story["event_id"]}],
            item_threads=[{"report_item_id": item_id, "thread_id": story["thread_id"]}],
            item_articles=[{"report_item_id": item_id, "article_id": story["article_id"], "source_line": story["title"]}],
            artifacts=[{"artifact_type": "markdown", "path": f"/tmp/{story['day']}.md"}],
        )


def _persist_same_scale_fresh_evidence(domain: str) -> None:
    fresh_batches = {
        "weekly": (
            "2026-05-31",
            [
                {
                    "id": "a-weekly-2026-W22-official-hbm",
                    "title": "Weekly official HBM capacity update",
                    "url": "https://example.com/weekly-hbm-capacity",
                    "source": "Example",
                    "published_at": "2026-05-31",
                    "locale": "en",
                    "entity_ids": ["samsung", "sk-hynix"],
                    "term_ids": ["hbm"],
                    "snippet": "Weekly fresh explore confirms HBM capacity pressure.",
                }
            ],
        ),
        "monthly": (
            "2026-05-31",
            [
                {
                    "id": "a-monthly-2026-05-supply-review",
                    "title": "Monthly supply review confirms HBM allocation pressure",
                    "url": "https://example.com/monthly-hbm-review",
                    "source": "Example",
                    "published_at": "2026-05-31",
                    "locale": "en",
                    "entity_ids": ["samsung", "micron"],
                    "term_ids": ["hbm"],
                    "snippet": "Monthly fresh explore confirms the trend.",
                }
            ],
        ),
        "quarterly": (
            "2026-06-30",
            [
                {
                    "id": "a-quarterly-2026-Q2-structure",
                    "title": "Quarterly HBM structure review",
                    "url": "https://example.com/quarterly-hbm-structure",
                    "source": "Example",
                    "published_at": "2026-06-30",
                    "locale": "en",
                    "entity_ids": ["samsung", "sk-hynix", "micron"],
                    "term_ids": ["hbm"],
                    "snippet": "Quarterly fresh explore frames HBM as structural.",
                }
            ],
        ),
        "yearly": (
            "2026-12-31",
            [
                {
                    "id": "a-yearly-2026-hbm-cycle",
                    "title": "Yearly HBM cycle review",
                    "url": "https://example.com/yearly-hbm-cycle",
                    "source": "Example",
                    "published_at": "2026-12-31",
                    "locale": "en",
                    "entity_ids": ["samsung", "sk-hynix", "micron"],
                    "term_ids": ["hbm"],
                    "snippet": "Yearly fresh explore summarizes the HBM cycle.",
                }
            ],
        ),
    }
    for scale, (run_date, articles) in fresh_batches.items():
        upsert_articles(
            domain,
            articles,
            run_date,
            artifact_path=f"/tmp/{scale}-fresh-articles.jsonl",
            scale=scale,
        )


def _run_scale_cascade(domain: str) -> list[dict[str, Any]]:
    results = []
    for scale, period in CASCADE_PERIODS:
        results.append(synthesize_cascade_report(domain, scale, period))
    return results
