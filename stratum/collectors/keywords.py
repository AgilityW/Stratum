"""Domain keyword extraction — shared by all collectors.

Reads companies and terms from domain.yaml, returns a flat lowercase
keyword list used for article filtering in RSS, direct_fetch, and browser
collectors.

Domain-scoped: each domain.yaml defines its own keywords.
Storage keywords ≠ robot keywords.
"""

import os
import yaml


def load_keywords(domain: str, workspace: str) -> list[str]:
    """Extract normalized keywords from domain.yaml.
    
    Sources:
    - companies.*.aliases.*  → all locale names (en, zh-CN, ja...)
    - terms.*.aliases.*      → all locale names
    - terms.*.id             → term IDs as fallback
    
    Returns: Lowercase, deduplicated, longest-first sorted list.
    """
    path = os.path.join(workspace, "domains", domain, "domain.yaml")
    if not os.path.exists(path):
        return []

    with open(path) as f:
        data = yaml.safe_load(f)

    keywords: set[str] = set()

    # Company names (all locales)
    for comp in data.get("companies", []):
        for name in comp.get("aliases", {}).values():
            if name:
                keywords.add(name.lower())

    # Technology terms
    for term in data.get("terms", []):
        for name in term.get("aliases", {}).values():
            if name:
                keywords.add(name.lower())
        tid = term.get("id", "")
        if tid:
            keywords.add(tid.lower())

    # Filter: remove very short/noisy keywords
    filtered = {k for k in keywords if len(k) >= 3}
    # Longest first — enables greedy matching
    return sorted(filtered, key=len, reverse=True)


def match_keywords(title: str, snippet: str, keywords: list[str]) -> bool:
    """Check if article text matches any domain keyword.
    
    Longest-first to prioritize specific terms (e.g., 'sk hynix' 
    before 'hynix'). Skip if keywords list is empty (pass-through mode).
    """
    if not keywords:
        return True

    text = f"{title} {snippet}".lower()
    for kw in keywords:
        if kw in text:
            return True
    return False
