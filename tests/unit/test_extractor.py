"""Unit tests for extractor.py — Entity/Term/Channel extraction heuristics."""

from graph import SourceGraph, EntityNode, TermNode, EntityType, TermType
from extractor import (
    SearchItem, EntityExtractor, TermExtractor, ChannelExtractor,
    EntityCandidate, TermCandidate, ChannelCandidate,
)


class TestSearchItem:
    def test_defaults(self):
        item = SearchItem(title="Test", url="https://a.com", snippet="x")
        assert item.source_tier == "C"
        assert item.engine == ""
        assert item.date == ""


class TestEntityExtractor:
    def test_extract_company_names_en(self, empty_graph):
        items = [
            SearchItem(
                title="Samsung Electronics Inc announces new chip",
                url="https://example.com/1",
                snippet="Samsung Electronics Inc is the largest memory maker.",
                source_tier="A",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        # regex strips trailing dots from company names
        assert "Samsung Electronics Inc" in candidates
        c = candidates["Samsung Electronics Inc"]
        assert c.occurrences == 2  # title + snippet
        assert c.source_tiers == ["A"]

    def test_extract_company_names_zh(self, empty_graph):
        items = [
            SearchItem(
                title="长鑫存储发布DDR5",
                url="https://example.com/1",
                snippet="长鑫存储采用12nm制程。",
                source_tier="A",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        assert "长鑫存储" in candidates

    def test_extract_product_codes(self, empty_graph):
        items = [
            SearchItem(
                title="NVIDIA HBM4 memory with RTX 5090",
                url="https://example.com/1",
                snippet="The RTX 5090 and HBM4 represent next-gen products.",
                source_tier="B",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        assert "RTX 5090" in candidates
        c = candidates["RTX 5090"]
        assert c.type == EntityType.PRODUCT

    def test_tracks_existing_nodes(self, empty_graph):
        """Extractor returns candidates even when entity exists in graph,
        so evolution can evaluate WATCH→ACTIVE upgrades."""
        empty_graph.add_entity(EntityNode(
            id="samsung", aliases={"en": "Samsung Electronics Inc"},
        ))
        items = [
            SearchItem(
                title="Samsung Electronics Inc Q2 results",
                url="https://example.com/1",
                snippet="Samsung Electronics Inc reports record profit.",
                source_tier="A",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        assert "Samsung Electronics Inc" in candidates  # still returned

    def test_filters_stop_words(self, empty_graph):
        items = [
            SearchItem(
                title="The company announced high performance chips",
                url="https://example.com/1",
                snippet="The company expects growth this year.",
                source_tier="C",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        # "the company" and "this year" should be filtered
        assert "The Company" not in candidates

    def test_skips_common_abbreviations(self, empty_graph):
        """Product codes that are common abbreviations should be skipped."""
        items = [
            SearchItem(
                title="GPU and CPU market trends",
                url="https://example.com/1",
                snippet="AI and 5G drive demand for GPUs and CPUs.",
                source_tier="C",
            ),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        # "CPU", "GPU" are in _STOP_CODES
        assert "CPU" not in candidates
        assert "GPU" not in candidates

    def test_deduplicates_source_urls(self, empty_graph):
        items = [
            SearchItem(title="Samsung Electronics Inc A", url="https://a.com/1",
                       snippet="x", source_tier="A"),
            SearchItem(title="Samsung Electronics Inc B", url="https://a.com/1",
                       snippet="x", source_tier="A"),
        ]
        candidates = EntityExtractor().extract(items, empty_graph)
        c = candidates["Samsung Electronics Inc"]
        assert len(c.source_urls) == 1  # deduplicated


class TestTermExtractor:
    def test_extract_metrics(self, empty_graph):
        items = [
            SearchItem(
                title="HBM4 achieves 1.5TB/s bandwidth",
                url="https://example.com/1",
                snippet="The new chip reaches 36GB capacity and 1024GB/s.",
                source_tier="A",
            ),
        ]
        candidates = TermExtractor().extract(items, empty_graph)
        # Should find numeric metrics
        assert "1.5TB/s" in candidates or "36GB" in candidates or "1024GB/s" in candidates

    def test_extract_tech_codes(self, empty_graph):
        items = [
            SearchItem(
                title="HBM4 and CXL 3.0 integration",
                url="https://example.com/1",
                snippet="CoWoS and PCIe Gen6 adoption accelerates.",
                source_tier="B",
            ),
        ]
        candidates = TermExtractor().extract(items, empty_graph)
        # HBM4, CXL are not in _STOP_CODES and match code pattern
        assert "HBM4" in candidates

    def test_extract_named_techniques(self, empty_graph):
        items = [
            SearchItem(
                title="Cell Multi-Bonding Technology explained",
                url="https://example.com/1",
                snippet="Advanced Packaging Architecture and Hybrid Bonding.",
                source_tier="B",
            ),
        ]
        candidates = TermExtractor().extract(items, empty_graph)
        # Should match named patterns ending in Technology/Architecture/etc.
        found = any(
            "Multi-Bonding" in name or "Packaging" in name or "Bonding" in name
            for name in candidates
        )
        assert found, f"Candidates: {list(candidates.keys())}"

    def test_co_occurrence_with_known_terms(self):
        g = SourceGraph("test")
        g.add_term(TermNode(id="hbm4", aliases={"en": "HBM4"}))
        g.add_term(TermNode(id="cowos", aliases={"en": "CoWoS"}))

        items = [
            SearchItem(
                title="HBM4 production using CoWoS packaging",
                url="https://example.com/1",
                snippet="HBM4 and CoWoS are essential.",
                source_tier="A",
            ),
        ]
        candidates = TermExtractor().extract(items, g)
        # HBM4 should have CoWoS as co-occurring known term
        hbm4_candidate = candidates.get("HBM4")
        if hbm4_candidate:
            assert "cowos" in hbm4_candidate.co_occurring_known_terms

    def test_extract_chinese_tech_terms(self, empty_graph):
        items = [
            SearchItem(
                title="先进制程技术突破",
                url="https://example.com/1",
                snippet="制程工艺和封装技术取得进展。",
                source_tier="B",
            ),
        ]
        candidates = TermExtractor().extract(items, empty_graph)
        # Should find Chinese tech terms with 制/芯/晶/封/etc.
        found = any("制程" in name or "封装" in name for name in candidates)
        assert found, f"Candidates: {list(candidates.keys())}"

    def test_tracks_existing_terms(self, empty_graph):
        empty_graph.add_term(TermNode(id="hbm4", aliases={"en": "HBM4"}))
        items = [
            SearchItem(title="HBM4 bandwidth", url="https://example.com/1",
                       snippet="HBM4 achieves record bandwidth.", source_tier="A"),
        ]
        candidates = TermExtractor().extract(items, empty_graph)
        assert "HBM4" in candidates  # still returned for evolution evaluation


class TestChannelExtractor:
    def test_extract_new_domains(self, empty_graph):
        items = [
            SearchItem(title="News 1", url="https://skhynix-news.com/a",
                       snippet="x", source_tier="A"),
            SearchItem(title="News 2", url="https://skhynix-news.com/b",
                       snippet="y", source_tier="A"),
        ]
        candidates = ChannelExtractor().extract(items, empty_graph)
        assert len(candidates) >= 1
        c = candidates.get("skhynix-news.com")
        assert c is not None
        assert c.article_count == 2
        assert c.type.name in ("NEWSROOM", "MEDIA")

    def test_skips_known_domains(self, empty_graph):
        from graph import ChannelNode, ChannelType
        empty_graph.add_channel(ChannelNode(
            id="known", url="https://semiconductor-today.com",
        ))
        items = [
            SearchItem(title="A", url="https://semiconductor-today.com/1",
                       snippet="x", source_tier="B"),
            SearchItem(title="B", url="https://semiconductor-today.com/2",
                       snippet="y", source_tier="B"),
        ]
        candidates = ChannelExtractor().extract(items, empty_graph)
        assert "semiconductor-today.com" not in candidates

    def test_filters_noise_domains(self, empty_graph):
        items = [
            SearchItem(title="Tweet", url="https://x.com/user/123",
                       snippet="x", source_tier="D"),
            SearchItem(title="Tweet2", url="https://x.com/user/456",
                       snippet="y", source_tier="D"),
            SearchItem(title="Reddit", url="https://reddit.com/r/hardware",
                       snippet="z", source_tier="D"),
        ]
        candidates = ChannelExtractor().extract(items, empty_graph)
        assert "x.com" not in candidates
        assert "reddit.com" not in candidates

    def test_requires_minimum_articles(self, empty_graph):
        items = [
            SearchItem(title="One-off", url="https://randomblog.com/1",
                       snippet="x", source_tier="C"),
        ]
        candidates = ChannelExtractor().extract(items, empty_graph)
        assert len(candidates) == 0

    def test_classifies_analyst_domains(self, empty_graph):
        from extractor import ChannelType
        items = [
            SearchItem(title="Report", url="https://www.trendforce.com/report1",
                       snippet="x", source_tier="A"),
            SearchItem(title="Report2", url="https://www.trendforce.com/report2",
                       snippet="y", source_tier="A"),
        ]
        candidates = ChannelExtractor().extract(items, empty_graph)
        c = candidates.get("trendforce.com")
        assert c is not None
        assert c.type == ChannelType.ANALYST
