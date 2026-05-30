"""Source registry reader — loads source definitions from domain.yaml.

Domain-scoped: each domain defines its own sources in domain.yaml.
The registry is the single source of truth for what to fetch and how.
"""

import os
import yaml
from typing import Optional


DEFAULT_KEY_ALIASES = {
    "max_articles_per_url": "max_articles",
    "timeout_seconds": "timeout",
}


def load_source_registry(domain: str, workspace: str) -> dict:
    """Load source_registry section from domain.yaml.
    
    Returns: {
        'sources': [...],
        'defaults': {...}
    }
    """
    path = os.path.join(workspace, "domains", domain, "domain.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("source_registry", {})


def _apply_access_defaults(source: dict, defaults: dict) -> dict:
    """Return a source copy with its access defaults applied."""
    access = source.get("access", "")
    access_defaults = defaults.get(access, {}) if isinstance(defaults, dict) else {}
    merged = dict(source)

    for key, value in access_defaults.items():
        target_key = DEFAULT_KEY_ALIASES.get(key, key)
        merged.setdefault(target_key, value)
        if target_key != key:
            merged.setdefault(key, value)

    return merged


def get_active_sources(domain: str, workspace: str, access: Optional[str] = None) -> list[dict]:
    """Return active sources, optionally filtered by access pattern."""
    registry = load_source_registry(domain, workspace)
    sources = registry.get("sources", [])
    defaults = registry.get("defaults", {})
    
    active = [_apply_access_defaults(s, defaults) for s in sources if s.get("status") == "active"]
    if access:
        active = [s for s in active if s.get("access") == access]
    
    return active
