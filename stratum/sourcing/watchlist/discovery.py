"""Review-only discovery of watchlist source candidates."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

import requests

from stratum.sourcing.watchlist.registry import load_source_registry


FEED_LINK_RE = re.compile(
    r'<link[^>]+(?:type=["\']application/(?:rss|atom)\+xml["\']|rel=["\']alternate["\'])[^>]+>',
    re.IGNORECASE,
)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
COMMON_FEED_PATHS = ("/feed/", "/rss/", "/atom.xml", "/news/rss")
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/news-sitemap.xml", "/sitemap_index.xml")


@dataclass(frozen=True)
class SourceCandidate:
    """Reviewable source candidate; never auto-enabled."""

    source_id: str
    url: str
    access: str
    reason: str
    status: str = "review"

    def to_dict(self) -> dict:
        return asdict(self)


def discover_source_candidates(source: dict, timeout: int = 10) -> list[SourceCandidate]:
    """Inspect one configured source URL for feed/sitemap candidates."""
    source_id = str(source.get("id") or "unknown")
    candidates: list[SourceCandidate] = []
    seen: set[tuple[str, str]] = set()
    headers = {"User-Agent": "Stratum/1.0 (source candidate discovery)"}

    def add(url: str, access: str, reason: str) -> None:
        key = (access, url)
        if key in seen:
            return
        seen.add(key)
        candidates.append(SourceCandidate(source_id, url, access, reason))

    for base_url in source.get("urls", []) or []:
        try:
            resp = requests.get(base_url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            for tag in FEED_LINK_RE.findall(resp.text):
                href = HREF_RE.search(tag)
                if href:
                    add(urljoin(base_url, href.group(1)), "rss", "html alternate feed link")
        except requests.RequestException:
            pass

        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        for path in COMMON_FEED_PATHS:
            add(urljoin(origin, path), "rss", "common feed path")
        for path in COMMON_SITEMAP_PATHS:
            add(urljoin(origin, path), "sitemap", "common sitemap path")

    return candidates


def discover_registry_candidates(
    domain: str,
    workspace: str,
    *,
    include_active: bool = True,
    include_review: bool = True,
    timeout: int = 10,
) -> list[SourceCandidate]:
    """Discover reviewable feed/sitemap candidates from a domain source registry."""
    registry = load_source_registry(domain, workspace)
    sources: list[dict] = []
    if include_active:
        sources.extend(registry.get("sources", []) or [])
    if include_review:
        sources.extend(registry.get("candidate_sources", []) or [])

    candidates: list[SourceCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        for candidate in discover_source_candidates(source, timeout=timeout):
            key = (candidate.source_id, candidate.access, candidate.url)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def write_review_queue(candidates: list[SourceCandidate], path: str) -> None:
    """Write review-only candidates as JSONL."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        for candidate in candidates:
            f.write(json.dumps(candidate.to_dict(), ensure_ascii=False) + "\n")
