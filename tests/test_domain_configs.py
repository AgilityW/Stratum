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
