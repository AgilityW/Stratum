"""Domain configuration integrity tests."""

from pathlib import Path
from urllib.parse import urlparse

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOMAINS = PROJECT_ROOT / "domains"


def _domain_dirs() -> list[Path]:
    return sorted(path for path in DOMAINS.iterdir() if path.is_dir())


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def test_domain_yaml_does_not_duplicate_query_templates():
    """Search owns query templates in queries.yaml to avoid split-brain strategy."""
    for domain_dir in _domain_dirs():
        domain_cfg = _load_yaml(domain_dir / "domain.yaml")
        assert "seed_queries" not in domain_cfg, domain_dir.name
        assert "gap_searches" not in domain_cfg, domain_dir.name


def test_queries_yaml_uses_current_query_schema_only():
    """queries.yaml should not keep legacy split-brain query sections."""
    for domain_dir in _domain_dirs():
        queries_cfg = _load_yaml(domain_dir / "queries.yaml")
        assert "seed_queries" not in queries_cfg, domain_dir.name
        assert "gap_searches" not in queries_cfg, domain_dir.name
        assert "queries" in queries_cfg, domain_dir.name


def test_every_domain_has_queries_yaml_with_supported_query_strategy():
    for domain_dir in _domain_dirs():
        queries_path = domain_dir / "queries.yaml"
        assert queries_path.exists(), domain_dir.name

        queries_cfg = _load_yaml(queries_path)
        intent_queries = queries_cfg.get("queries")

        assert isinstance(intent_queries, dict), domain_dir.name
        assert any(
            locale_queries
            for dimension_map in intent_queries.values()
            if isinstance(dimension_map, dict)
            for locale_map in dimension_map.values()
            if isinstance(locale_map, dict)
            for locale_queries in locale_map.values()
        ), domain_dir.name


def test_domain_queries_use_structured_domain_filters():
    """Source-scoped searches should use include_domains, not site: in text."""
    for domain_dir in _domain_dirs():
        queries_cfg = _load_yaml(domain_dir / "queries.yaml")
        for query in _iter_query_items(queries_cfg.get("queries", {})):
            text = query.get("text", query.get("query", "")) if isinstance(query, dict) else str(query)
            assert "site:" not in text.lower(), (domain_dir.name, text)
            if isinstance(query, dict) and ("include_domains" in query or "domains" in query):
                domains = query.get("include_domains", query.get("domains"))
                if isinstance(domains, str):
                    domains = [domains]
                assert isinstance(domains, list), (domain_dir.name, query)
                for domain in domains:
                    assert isinstance(domain, str) and domain.strip(), (domain_dir.name, query)
                    assert _is_bare_domain(domain), (domain_dir.name, query)


def _iter_query_items(node):
    if isinstance(node, list):
        yield from node
        return
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_query_items(value)


def _is_bare_domain(value: str) -> bool:
    """Return True for host-only include_domains values."""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc or parsed.path
    return (
        value == host
        and "/" not in value
        and not any(char.isspace() for char in value)
        and "." in value
    )


def test_storage_source_registry_active_sources_are_collectable():
    domain_cfg = _load_yaml(DOMAINS / "storage" / "domain.yaml")
    sources = domain_cfg["source_registry"]["sources"]
    active = [src for src in sources if src.get("status") == "active"]

    assert active
    for source in active:
        assert source.get("id")
        assert source.get("urls")
        assert source.get("access") in {"direct_fetch", "rss", "browser"}
        assert source.get("locale")
        assert source.get("category") in {"newsroom", "blog", "media", "analyst", "official"}


def test_source_registry_budget_shape():
    """Validate optional acquisition budget parameters before runtime policy consumes them."""
    for domain_dir in _domain_dirs():
        domain_cfg = _load_yaml(domain_dir / "domain.yaml")
        budget = domain_cfg.get("source_registry", {}).get("budget", {})

        assert isinstance(budget, dict), domain_dir.name
        for integer_key in ("max_sources",):
            if integer_key in budget:
                assert isinstance(budget[integer_key], int) and budget[integer_key] >= 0, (
                    domain_dir.name,
                    integer_key,
                )
        if "max_total_cost" in budget:
            assert isinstance(budget["max_total_cost"], (int, float))
            assert budget["max_total_cost"] >= 0
        for map_key in ("min_per_access", "max_per_access"):
            access_counts = budget.get(map_key, {})
            assert isinstance(access_counts, dict), (domain_dir.name, map_key)
            for access, count in access_counts.items():
                assert isinstance(access, str) and access.strip(), (domain_dir.name, access)
                assert isinstance(count, int) and count >= 0, (domain_dir.name, access, count)
        access_costs = budget.get("access_costs", {})
        assert isinstance(access_costs, dict), domain_dir.name
        for access, cost in access_costs.items():
            assert isinstance(access, str) and access.strip(), (domain_dir.name, access)
            assert isinstance(cost, (int, float)) and cost >= 0, (domain_dir.name, access, cost)


def test_storage_review_candidate_sources_are_described():
    domain_cfg = _load_yaml(DOMAINS / "storage" / "domain.yaml")
    candidates = domain_cfg["source_registry"].get("candidate_sources", [])

    assert candidates
    for source in candidates:
        assert source.get("status") == "review"
        assert source.get("id")
        assert source.get("urls")
        assert source.get("access") in {"direct_fetch", "rss", "browser", "sitemap"}
        assert source.get("locale")
        assert source.get("category") in {"newsroom", "blog", "media", "analyst", "official"}
        assert source.get("expected_yield") in {"low", "medium", "high", "unknown"}
        assert source.get("date_quality") in {"low", "medium", "high", "unknown"}
        assert source.get("channel_owner")


def test_source_aliases_are_strings_or_domain_lists():
    """Validate source alias config shape before Validate consumes it."""
    for domain_dir in _domain_dirs():
        domain_cfg = _load_yaml(domain_dir / "domain.yaml")
        aliases = domain_cfg.get("pipeline", {}).get("source_aliases", {})

        assert isinstance(aliases, dict), domain_dir.name
        for label, value in aliases.items():
            assert isinstance(label, str) and label.strip(), (domain_dir.name, label)
            if isinstance(value, str):
                assert value.strip(), (domain_dir.name, label)
                continue
            assert isinstance(value, list), (domain_dir.name, label)
            assert value, (domain_dir.name, label)
            assert all(isinstance(item, str) and item.strip() for item in value), (
                domain_dir.name,
                label,
            )


def test_date_window_source_type_stale_days_shape():
    """Verify optional source-type freshness windows before Verify consumes them."""
    for domain_dir in _domain_dirs():
        domain_cfg = _load_yaml(domain_dir / "domain.yaml")
        date_window = domain_cfg.get("pipeline", {}).get("date_window", {})
        windows = date_window.get("source_type_stale_days", {})

        assert isinstance(windows, dict), domain_dir.name
        for source_type, stale_days in windows.items():
            assert isinstance(source_type, str) and source_type.strip(), domain_dir.name
            assert isinstance(stale_days, int) and stale_days >= 0, (
                domain_dir.name,
                source_type,
                stale_days,
            )


def test_storage_queries_cover_core_briefing_dimensions():
    queries_cfg = _load_yaml(DOMAINS / "storage" / "queries.yaml")
    detection = queries_cfg.get("queries", {}).get("detection", {})

    assert {
        "technology",
        "product",
        "platform_demand",
        "supply_chain",
        "market_pricing",
        "financial",
    }.issubset(detection)


def test_storage_signal_awareness_config_has_topics_and_anchors():
    awareness_cfg = _load_yaml(DOMAINS / "storage" / "signal_awareness.yaml")

    assert isinstance(awareness_cfg.get("topic_rules"), list)
    assert awareness_cfg["topic_rules"]
    for rule in awareness_cfg["topic_rules"]:
        assert rule.get("id")
        assert rule.get("keywords")

    assert isinstance(awareness_cfg.get("anchors"), list)
    assert awareness_cfg["anchors"]
    for anchor in awareness_cfg["anchors"]:
        assert anchor.get("id")
        assert anchor.get("name")
        assert anchor.get("aliases")
        assert anchor.get("query_terms")
