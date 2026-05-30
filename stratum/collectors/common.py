"""Shared collector helpers for source identity and type normalization."""

from urllib.parse import urlparse


def extract_domain(url: str) -> str:
    """Return a normalized hostname for a result URL."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def normalize_source_type(category: str) -> str:
    """Map source-registry collection categories to canonical source types."""
    category = (category or "").strip().lower()
    aliases = {
        "newsroom": "official",
        "press": "official",
        "press_release": "official",
        "press-release": "official",
        "rss": "media",
        "news": "media",
    }
    canonical = aliases.get(category, category)
    if canonical in {"official", "analyst", "media", "blog", "social", "unknown"}:
        return canonical
    return "unknown"
