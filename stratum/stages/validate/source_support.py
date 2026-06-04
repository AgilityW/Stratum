"""Source support matching policy for Validate stage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from stratum.sourcing.discovery import source_pattern_matches


CST = timezone(timedelta(hours=8))
BACKGROUND_QUALITY_FLAGS = {"BACKGROUND_STALE", "BACKGROUND_NO_DATE"}

TOKEN_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "said",
    "update", "market", "prices", "price", "news", "report", "reports",
    "announced", "announces", "company", "industry", "memory",
}

TOKEN_ALIASES = {
    "contract": {"合约"},
    "supply": {"供应"},
    "chain": {"链"},
    "seasonality": {"季节", "季节性"},
    "seasonal": {"季节", "季节性"},
    "hike": {"上涨"},
    "hikes": {"上涨"},
    "increase": {"上涨"},
    "increases": {"上涨"},
    "increased": {"上涨"},
    "quarter": {"季度"},
    "q1": {"一季度", "第一季度"},
    "1q26": {"一季度", "第一季度", "2026"},
    "dram": {"dram"},
    "nand": {"nand"},
    "hbm": {"hbm"},
}


@dataclass(frozen=True)
class SourceSupportMatcher:
    """Match cited sources to article records and item context."""

    def article_source_values(self, article: dict) -> list[str]:
        values = [
            article.get("source", ""),
            article.get("source_domain", ""),
            self.domain_from_url(article.get("url", "")),
        ]
        return [v.strip().lower() for v in values if v and v.strip()]

    def article_matches_source(self, article: dict, src_lower: str, source_aliases: dict) -> bool:
        article_sources = self.article_source_values(article)
        alias_patterns = self.source_alias_patterns(source_aliases.get(src_lower))
        if alias_patterns:
            if any(
                self.source_value_matches_pattern(asrc, pattern)
                for pattern in alias_patterns
                for asrc in article_sources
            ):
                return True
        if self.looks_like_domain_label(src_lower):
            return any(self.source_value_matches_pattern(asrc, src_lower) for asrc in article_sources)
        return src_lower in article_sources

    def item_article_alignment(self, item: dict, article: dict) -> tuple[bool, set[str]]:
        item_text = f"{item.get('title', '')} {' '.join(item.get('body', []))}"
        article_text = (
            f"{article.get('title', '')} "
            f"{article.get('snippet', '')} "
            f"{article.get('extracted_summary', '')}"
        )
        item_tokens = self.content_tokens(item_text)
        article_tokens = self.content_tokens(article_text)
        if not item_tokens:
            return True, set()
        if not article_tokens:
            return False, set()

        overlap = item_tokens & article_tokens
        if any(self.is_strong_alignment_token(token) for token in overlap):
            return True, overlap
        if len(overlap) >= 2:
            return True, overlap
        if overlap and len(overlap) / max(1, min(len(item_tokens), len(article_tokens))) >= 0.34:
            return True, overlap
        return False, overlap

    def content_tokens(self, text: str) -> set[str]:
        tokens: set[str] = set()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text.lower()):
            token = token.strip(".-")
            aliases = TOKEN_ALIASES.get(token, set())
            if aliases:
                tokens.update(aliases)
            if len(token) < 2 or token in TOKEN_STOPWORDS:
                continue
            tokens.add(token)
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
                for size in (2, 3, 4):
                    for i in range(len(token) - size + 1):
                        tokens.add(token[i:i + size])
        return tokens

    def is_strong_alignment_token(self, token: str) -> bool:
        token = token.strip().lower()
        if len(token) < 4:
            return False
        if not re.search(r"[a-z]", token) or not re.search(r"\d", token):
            return False
        return token not in TOKEN_STOPWORDS

    @staticmethod
    def domain_from_url(url: str) -> str:
        if not url:
            return ""
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        return host

    @staticmethod
    def source_alias_patterns(alias_value) -> list[str]:
        if not alias_value:
            return []
        if isinstance(alias_value, str):
            values = [alias_value]
        elif isinstance(alias_value, (list, tuple, set)):
            values = alias_value
        else:
            return []
        return [str(value).strip().lower() for value in values if str(value).strip()]

    @staticmethod
    def source_value_matches_pattern(source_value: str, pattern: str) -> bool:
        source_value = (source_value or "").strip().lower()
        pattern = (pattern or "").strip().lower()
        if not source_value or not pattern:
            return False
        return source_pattern_matches(f"https://{source_value}", pattern)

    @staticmethod
    def looks_like_domain_label(source_label: str) -> bool:
        value = source_label.strip().lower()
        return "." in value or value.startswith(("www.", "m."))


@dataclass(frozen=True)
class SourceDatePolicy:
    """Parse source-line and article dates for support validation."""

    def parse_cited_date_range(self, cited_date: str) -> tuple[datetime, datetime] | None:
        cn_range = re.search(
            r'(\d{4})年(\d{1,2})月(\d{1,2})\s*(?:-|~|至|到)\s*(\d{1,2})日',
            cited_date,
        )
        if cn_range:
            y, m, start_d, end_d = map(int, cn_range.groups())
            start = datetime(y, m, start_d).replace(tzinfo=CST)
            end = datetime(y, m, end_d).replace(tzinfo=CST)
            return (start, end) if start <= end else (end, start)

        cn_full_range = re.search(
            r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(?:-|~|至|到)\s*'
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            cited_date,
        )
        if cn_full_range:
            y1, m1, d1, y2, m2, d2 = map(int, cn_full_range.groups())
            start = datetime(y1, m1, d1).replace(tzinfo=CST)
            end = datetime(y2, m2, d2).replace(tzinfo=CST)
            return (start, end) if start <= end else (end, start)

        iso_range = re.search(
            r'(\d{4}-\d{2}-\d{2})\s*(?:/|-|~|至|到)\s*(\d{4}-\d{2}-\d{2})',
            cited_date,
        )
        if iso_range:
            start = datetime.fromisoformat(iso_range.group(1)).replace(tzinfo=CST)
            end = datetime.fromisoformat(iso_range.group(2)).replace(tzinfo=CST)
            return (start, end) if start <= end else (end, start)

        single = self.parse_cited_date(cited_date)
        if single:
            return single, single
        return None

    def parse_cited_date(self, cited_date: str) -> datetime | None:
        cn_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', cited_date)
        if cn_match:
            y, m, d = map(int, cn_match.groups())
            return datetime(y, m, d).replace(tzinfo=CST)

        iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', cited_date)
        if iso_match:
            return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=CST)

        return None

    def parse_article_date(self, article: dict) -> datetime | None:
        raw_date = (
            article.get("published_at")
            or article.get("datePublished")
            or article.get("date")
            or ""
        )
        if not raw_date:
            return None

        text = str(raw_date).strip()
        cn_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if cn_match:
            y, m, d = map(int, cn_match.groups())
            return datetime(y, m, d).replace(tzinfo=CST)

        iso_text = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(iso_text).astimezone(CST)
        except ValueError:
            iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
            if iso_match:
                return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=CST)
        return None

    @staticmethod
    def is_background_article(article: dict) -> bool:
        flags = set(article.get("quality_flags") or [])
        return bool(flags & BACKGROUND_QUALITY_FLAGS)
