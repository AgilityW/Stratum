"""Source/article alignment algorithms for Edit output repair."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceAlignmentConfig:
    """Thresholds for matching generated items back to evidence articles."""

    min_overlap_score: float = 0.35


@dataclass(frozen=True)
class SourceAlignment:
    """Structured source alignment result."""

    article: dict | None
    score: float
    reason: str

    @property
    def matched(self) -> bool:
        return self.article is not None


class SourceAlignmentMatcher:
    """Match generated report items and cited source labels to articles."""

    def __init__(self, config: SourceAlignmentConfig | None = None):
        self.config = config or SourceAlignmentConfig()

    def article_source_label(self, article: dict) -> str:
        source = article.get("source") or article.get("source_domain") or ""
        if source:
            return str(source).strip()
        url = article.get("url", "")
        if not url:
            return ""
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        return host

    def source_matches_label(self, article: dict, label: str) -> bool:
        article_source = self.article_source_label(article).lower()
        source_label = label.lower().strip()
        if article_source == source_label:
            return True
        url = str(article.get("url") or "").lower()
        return bool(source_label and source_label in url)

    def best_article_for_item(
        self,
        title: str,
        body_lines: list[str],
        articles: list[dict],
    ) -> dict | None:
        return self.align_item(title, body_lines, articles).article

    def best_article_for_source_item(
        self,
        source: str,
        title: str,
        body_lines: list[str],
        articles: list[dict],
    ) -> dict | None:
        source_articles = [article for article in articles if self.source_matches_label(article, source)]
        return self.best_article_for_item(title, body_lines, source_articles)

    def align_item(
        self,
        title: str,
        body_lines: list[str],
        articles: list[dict],
    ) -> SourceAlignment:
        item_tokens = self.match_tokens(f"{title} {' '.join(body_lines)}")
        if not item_tokens:
            return SourceAlignment(None, 0.0, "no item tokens")

        best_article = None
        best_score = 0.0
        for article in articles:
            article_tokens = self.match_tokens(
                f"{article.get('title', '')} {article.get('snippet', '')}"
            )
            if not article_tokens:
                continue
            overlap = len(item_tokens & article_tokens)
            score = overlap / max(1, min(len(item_tokens), len(article_tokens)))
            if score > best_score:
                best_score = score
                best_article = article

        if best_article and best_score >= self.config.min_overlap_score:
            return SourceAlignment(best_article, best_score, "token overlap")
        return SourceAlignment(None, best_score, "below threshold")

    def match_tokens(self, text: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text.lower()):
            if len(token) >= 2:
                tokens.add(token)
        return tokens
