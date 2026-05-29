"""Source registry reader — loads source definitions from domain.yaml.

Domain-scoped: each domain defines its own sources in domain.yaml.
The registry is the single source of truth for what to fetch and how.
"""

import os
import yaml
from typing import Optional


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


def get_active_sources(domain: str, workspace: str, access: Optional[str] = None) -> list[dict]:
    """Return active sources, optionally filtered by access pattern."""
    registry = load_source_registry(domain, workspace)
    sources = registry.get("sources", [])
    
    active = [s for s in sources if s.get("status") == "active"]
    if access:
        active = [s for s in active if s.get("access") == access]
    
    return active
