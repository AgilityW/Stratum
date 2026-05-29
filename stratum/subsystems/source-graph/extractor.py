"""
Entity/Term/Channel extractor from search results.

Takes raw search result items (title + snippet + url + date) and
identifies candidate nodes not yet in the graph. Uses heuristics,
not LLM — fast, offline, reproducible.

Domain-agnostic: knows regex patterns for company/product/tech names,
but knows nothing about "storage" or any specific industry.
"""

from __future__ import annotations

import re
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus,
)


# ── Candidate Types ────────────────────────────────────────

@dataclass
class EntityCandidate:
    raw_name: str
    type: EntityType = EntityType.COMPANY
    occurrences: int = 1
    source_urls: list[str] = field(default_factory=list)
    source_tiers: list[str] = field(default_factory=list)  # A/B/C/D
    contexts: list[str] = field(default_factory=list)  # surrounding snippets


@dataclass
class TermCandidate:
    raw_name: str
    type: TermType = TermType.TECHNOLOGY
    occurrences: int = 1
    co_occurring_known_terms: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)


@dataclass
class ChannelCandidate:
    domain: str
    url: str
    type: ChannelType = ChannelType.MEDIA
    article_count: int = 1
    article_urls: list[str] = field(default_factory=list)
    snippet_preview: str = ""


# ── Result Item ────────────────────────────────────────────

@dataclass
class SearchItem:
    """Normalized search result from any engine."""
    title: str
    url: str
    snippet: str
    date: str = ""
    engine: str = ""
    source_tier: str = "C"  # A=official, B=major-media, C=blog, D=social


# ── Patterns ───────────────────────────────────────────────

# Company name patterns
COMPANY_SUFFIXES = (
    r"(?:Inc\.?|Corp\.?|Ltd\.?|LLC|PLC|GmbH|S\.A\.|Co\.?|"
    r"科技|电子|半导体|存储|光电|微电子|集团|股份|有限|控股)"
)

# Product code patterns (all-caps alphanumeric with numbers)
PRODUCT_PATTERN = re.compile(
    r"\b([A-Z]{2,6}[\s-]?\d{2,5}[A-Z]?\d*[A-Z]?)\b"
)

# Known tech metric suffixes
TECH_METRIC_PATTERNS = [
    re.compile(r"(\d+[\s]?(?:nm|µm|TB|GB|MB|TB/s|GB/s|Gbps|Tbps|MHz|GHz|W|mW))"),
    re.compile(r"(\d+[\s]?(?:layer|core|bit|cell))"),
]

# Terms that indicate the surrounding text is technical
TECH_INDICATORS = [
    "process", "node", "architecture", "transistor", "wafer", "die",
    "fabrication", "lithography", "yield", "packaging", "interconnect",
    "bandwidth", "throughput", "latency", "interface", "protocol",
    "制程", "工艺", "架构", "晶圆", "封装", "良率", "堆叠", "层",
]


# ── Extractor ──────────────────────────────────────────────

class EntityExtractor:
    """Extract candidate company/product/person/org names from search results."""

    def extract(self, items: list[SearchItem], graph: SourceGraph) -> dict[str, EntityCandidate]:
        candidates: dict[str, EntityCandidate] = {}

        for item in items:
            text = f"{item.title} {item.snippet}"
            for name in self._extract_company_names(text):
                # Still track existing nodes so evolution can evaluate WATCH→ACTIVE upgrade
                candidates.setdefault(name, EntityCandidate(raw_name=name))
                c = candidates[name]
                c.occurrences += 1
                if item.url not in c.source_urls:
                    c.source_urls.append(item.url)
                if item.source_tier not in c.source_tiers:
                    c.source_tiers.append(item.source_tier)

            for name, ptype in self._extract_product_codes(text):
                # Still track existing nodes so evolution can evaluate WATCH→ACTIVE upgrade
                candidates.setdefault(name, EntityCandidate(raw_name=name, type=ptype))
                c = candidates[name]
                c.occurrences += 1
                if item.url not in c.source_urls:
                    c.source_urls.append(item.url)

        return candidates

    @staticmethod
    def _extract_company_names(text: str) -> list[str]:
        """Heuristic: Capitalized multi-word phrases ending in known suffixes,
        or Chinese company names with known suffixes."""
        names = set()

        # English: "NVIDIA Corporation", "SK hynix Inc."
        pattern_en = re.compile(
            r"\b((?:[A-Z][a-z]+\s){1,4}(?:" + COMPANY_SUFFIXES + r"))\b"
        )
        for m in pattern_en.finditer(text):
            name = m.group(0).strip()
            # Exclude false positives: common words, too short
            if len(name.split()) >= 2 and name.lower() not in _STOP_WORDS:
                names.add(name)

        # Chinese: "XX科技", "XX电子", "XX半导体", "XX存储", "XX微"
        pattern_zh = re.compile(
            r"((?:[\u4e00-\u9fff]{2,8})(?:科技|电子|半导体|存储|光电|微电子|集团|股份|控股|资本))"
        )
        for m in pattern_zh.finditer(text):
            name = m.group(0)
            if len(name) >= 4:
                names.add(name)

        return list(names)

    @staticmethod
    def _extract_product_codes(text: str) -> list[tuple[str, EntityType]]:
        """Product codes like HBM4, RTX 5090, EPYC 9575F."""
        results = []
        for m in PRODUCT_PATTERN.finditer(text):
            code = m.group(0).strip()
            # Filter: must have digits, not be a common abbreviation
            if re.search(r"\d", code) and code.upper() not in _STOP_CODES:
                results.append((code, EntityType.PRODUCT))
        return results


class TermExtractor:
    """Extract candidate technology terms from search results."""

    def extract(self, items: list[SearchItem], graph: SourceGraph) -> dict[str, TermCandidate]:
        candidates: dict[str, TermCandidate] = {}
        all_known_terms = set(graph.terms.keys())

        for item in items:
            text = f"{item.title} {item.snippet}"

            # Extract tech metrics
            for pattern in TECH_METRIC_PATTERNS:
                for m in pattern.finditer(text):
                    name = m.group(0).strip()
                    # Still track existing terms so evolution can evaluate WATCH→ACTIVE upgrade
                    candidates.setdefault(name, TermCandidate(
                        raw_name=name, type=TermType.METRIC))
                    c = candidates[name]
                    c.occurrences += 1
                    if item.url not in c.source_urls:
                        c.source_urls.append(item.url)

            # Extract tech noun phrases: "Cell Multi-Bonding", "advanced packaging"
            for phrase in self._extract_tech_phrases(text):
                # Still track existing terms so evolution can evaluate WATCH→ACTIVE upgrade
                candidates.setdefault(phrase, TermCandidate(
                    raw_name=phrase, type=TermType.TECHNIQUE))
                c = candidates[phrase]
                c.occurrences += 1
                if item.url not in c.source_urls:
                    c.source_urls.append(item.url)

            # Compute co-occurrence with known terms
            for name in list(candidates.keys()):
                c = candidates[name]
                for known_term in all_known_terms:
                    node = graph.get_term(known_term)
                    if not node:
                        continue
                    for alias in node.aliases.values():
                        if alias.lower() in text.lower():
                            if known_term not in c.co_occurring_known_terms:
                                c.co_occurring_known_terms.append(known_term)

        return candidates

    @staticmethod
    def _extract_tech_phrases(text: str) -> list[str]:
        """Extract technical noun phrases — individual terms, not sentences."""
        phrases = set()

        # Pattern 1: All-caps technical codes (HBM4, PCIe6, CMB, CoPoS, LPDDR5X)
        code_pattern = re.compile(
            r'\b([A-Z]{2,8}(?:[\s-]?(?:Gen\s?)?\d+[A-Za-z]*(?:\.[A-Za-z\d]+)?)?)\b'
        )
        for m in code_pattern.finditer(text):
            code = m.group(0).strip()
            if len(code) >= 2 and code.upper() not in _STOP_CODES:
                phrases.add(code)

        # Pattern 2: Named techniques/technologies (ProperNoun + common noun combos)
        named_pattern = re.compile(
            r'\b((?:[A-Z][a-z]+\s){1,2}(?:Technology|Architecture|Fabric|Packaging|'
            r'Bonding|Memory|Storage|Computing|Interconnect|Protocol|Process))\b'
        )
        for m in named_pattern.finditer(text):
            phrase = m.group(0).strip()
            if len(phrase) > 8:
                phrases.add(phrase)

        # Pattern 3: Chinese technical terms (2-6 chars, contains tech chars)
        zh_tech_chars = r'[制芯晶封存算互连协处]'
        zh_pattern = re.compile(
            rf'(?:[\u4e00-\u9fff]{{1,3}}{zh_tech_chars}[\u4e00-\u9fff]{{1,4}})'
        )
        for m in zh_pattern.finditer(text):
            phrase = m.group(0).strip()
            if len(phrase) >= 3:
                phrases.add(phrase)

        return list(phrases)


class ChannelExtractor:
    """Extract candidate information channels from search result URLs."""

    def extract(self, items: list[SearchItem], graph: SourceGraph) -> dict[str, ChannelCandidate]:
        candidates: dict[str, ChannelCandidate] = {}
        known_domains = {urlparse(ch.url).netloc for ch in graph.channels.values() if ch.url}

        # Count per domain
        domain_items: dict[str, list[SearchItem]] = defaultdict(list)
        for item in items:
            parsed = urlparse(item.url)
            domain = parsed.netloc.replace("www.", "")
            if domain in known_domains:
                continue
            if _is_noise_domain(domain):
                continue
            domain_items[domain].append(item)

        for domain, ditem in domain_items.items():
            # Need at least 2 articles from same domain to be interesting
            if len(ditem) < 2:
                continue

            # Classify channel type
            ctype = _classify_domain(domain, ditem)

            representative = ditem[0]
            candidates[domain] = ChannelCandidate(
                domain=domain,
                url=f"https://{domain}",
                type=ctype,
                article_count=len(ditem),
                article_urls=[i.url for i in ditem],
                snippet_preview=representative.snippet[:200],
            )

        return candidates


# ── Helpers ────────────────────────────────────────────────

_STOP_WORDS = {
    "the company", "a corporation", "all rights", "this year",
    "next generation", "high performance", "real time",
}

_STOP_CODES = {
    "API", "CPU", "GPU", "SSD", "HDD", "RAM", "ROM", "I/O",
    "USB", "PCI", "DDR", "AI", "ML", "DL", "IoT", "5G", "4G", "WiFi",
    # NOTE: NAND, DRAM, HBM, CXL are NOT in STOP — they are actual tech terms we track
}

_STOP_PHRASES = {
    "the company announced", "this year the", "according to the",
    "in the first", "the global market", "the new technology",
}

_NOISE_DOMAINS = {
    "x.com", "twitter.com", "reddit.com", "facebook.com",
    "instagram.com", "youtube.com", "linkedin.com",
    "google.com", "bing.com", "yahoo.com",
    "amazon.com", "ebay.com", "wikipedia.org",
}


def _is_noise_domain(domain: str) -> bool:
    return any(n in domain for n in _NOISE_DOMAINS)


def _classify_domain(domain: str, items: list[SearchItem]) -> ChannelType:
    """Heuristic: classify domain based on URL structure and content patterns."""
    d = domain.lower()

    # Known analyst/research domains
    analyst_patterns = [
        "trendforce", "yolegroup", "counterpoint", "semianalysis",
        "omdia", "icinsights", "gartner", "idc", "dello",
    ]
    if any(p in d for p in analyst_patterns):
        return ChannelType.ANALYST

    # Newsroom: investor.*, *-ir.*, news.*, press.*
    ir_patterns = ["investor.", "-ir.", "newsroom.", "press."]
    if any(p in d for p in ir_patterns):
        return ChannelType.NEWSROOM

    # Blog
    blog_patterns = ["blog.", "blogs.", "/blog", "insights."]
    if any(p in d for p in blog_patterns):
        return ChannelType.BLOG

    # Research / standards bodies
    research_patterns = ["semi.org", "jedec", "ieee", "acm.org"]
    if any(p in d for p in research_patterns):
        return ChannelType.RESEARCH

    return ChannelType.MEDIA
