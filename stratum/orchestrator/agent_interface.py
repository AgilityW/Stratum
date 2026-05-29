"""
Agent Interface Contract — Stratum v5.0

Defines the interface between the deterministic pipeline and LLM-driven agent stages.
Pipeline stages 1 (Search) and 6 (Edit) require agent execution.
All other stages are deterministic pure functions.

This file is the CONTRACT — it defines what the agent must do, not how.
The pipeline.py calls agent stages via this interface.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


# ═══════════════════════════════════════════════════════════════════
# Stage 1: Agent Search
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SearchQuery:
    """A single search query for one locale."""
    query: str                          # Search query string
    locale: str                         # BCP 47 locale (en, zh-CN, ja, ko, ...)
    engine: str                         # Search engine (tavily, bocha, ...)


@dataclass
class SearchConfig:
    """Configuration for the agent search stage."""
    domain_id: str                      # e.g. 'storage'
    date: date                          # Run date
    queries: list[SearchQuery]          # Queries to execute (from queries.yaml)
    max_results_per_query: int = 5      # Results per query-locale pair


@dataclass
class RawSearchResult:
    """A single raw search result — matches the raw.json schema."""
    url: str
    title: str
    snippet: str
    datePublished: str = ""             # May be empty; enrich stage fills it
    engine: str = ""
    query_used: str = ""


@dataclass
class SearchOutput:
    """Output of the agent search stage → written to raw.json."""
    domain_id: str
    date: str                           # ISO date string
    results: list[RawSearchResult]
    stats: dict = field(default_factory=dict)  # {total, engines_used, queries_run}


# ═══════════════════════════════════════════════════════════════════
# Stage 6: Agent Edit
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EditConfig:
    """Configuration for the agent edit stage."""
    domain_id: str                      # e.g. 'storage'
    date: str                           # ISO date string
    prompt_path: str                    # Path to domains/{id}/prompts/daily.md
    articles_path: str                  # Path to articles.jsonl
    clusters_path: str                  # Path to clusters.json
    domain_config_path: str             # Path to domain.yaml
    max_items: int = 8                  # Max news items in briefing
    max_watch_items: int = 4            # Max watch items
    max_contrarian_items: int = 2       # Max contrarian signals


@dataclass
class EditOutput:
    """Output of the agent edit stage → written to briefing.md."""
    domain_id: str
    date: str
    markdown: str                       # The completed briefing.md content
    stats: dict = field(default_factory=dict)  # {items, watch_items, contrarian_items, sources_cited}


# ═══════════════════════════════════════════════════════════════════
# Pipeline Integration
# ═══════════════════════════════════════════════════════════════════

def build_search_config(domain_id: str, run_date: date,
                        queries_path: str, domain_config_path: str) -> SearchConfig:
    """
    Build SearchConfig from domain queries.yaml.
    Called by pipeline.py before Stage 1.

    Reads queries.yaml → builds SearchQuery list per locale.
    Returns SearchConfig ready for agent execution.
    """
    import yaml
    with open(queries_path) as f:
        query_data = yaml.safe_load(f)

    queries = []
    for locale, locale_queries in query_data.get("queries", {}).items():
        engine = query_data.get("engines", {}).get(locale, "tavily")
        for q in locale_queries:
            queries.append(SearchQuery(query=q, locale=locale, engine=engine))

    return SearchConfig(
        domain_id=domain_id,
        date=run_date,
        queries=queries,
    )


def build_edit_config(domain_id: str, run_date: str,
                      prompts_dir: str, articles_path: str,
                      clusters_path: str, domain_config_path: str) -> EditConfig:
    """
    Build EditConfig for the agent edit stage.
    Called by pipeline.py before Stage 6.

    Reads the daily prompt template from prompts_dir/daily.md.
    Returns EditConfig ready for agent execution.
    """
    import os
    prompt_path = os.path.join(prompts_dir, "daily.md")
    return EditConfig(
        domain_id=domain_id,
        date=run_date,
        prompt_path=prompt_path,
        articles_path=articles_path,
        clusters_path=clusters_path,
        domain_config_path=domain_config_path,
    )
