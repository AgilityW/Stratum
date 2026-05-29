"""Tests for Story Bridge — Agent EventThread → EventRecord conversion pipeline."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
# Also add orchestrator/ for story_bridge import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "orchestrator"))
import tempfile
import pytest
import json

from story_contracts import EventRecord
from repository import JsonlEventRepository, StateManager
from taxonomy import Taxonomy


# ── Fixtures ──

@pytest.fixture
def taxonomy_path():
    """Minimal taxonomy for tag extraction tests."""
    data = {
        "topics": [
            {"id": "hbm", "label": "HBM", "aliases": ["HBM4", "HBM3E", "High Bandwidth Memory"]},
            {"id": "ddr5", "label": "DDR5", "aliases": ["DDR5 SDRAM", "DDR5 DRAM"]},
            {"id": "nand", "label": "NAND", "aliases": ["NAND Flash", "3D NAND", "NAND"]},
            {"id": "ipo", "label": "IPO", "aliases": ["IPO", "上市", "科创板"]},
            {"id": "pricing", "label": "Pricing", "aliases": ["price", "pricing", "ASP"]},
            {"id": "supply-chain", "label": "Supply Chain", "aliases": ["supply", "equipment"]},
        ],
        "entities": [
            {"id": "samsung", "label": "Samsung", "type": "company",
             "aliases": ["Samsung", "三星", "SEC"]},
            {"id": "sk-hynix", "label": "SK Hynix", "type": "company",
             "aliases": ["SK Hynix", "SK海力士", "海力士"]},
            {"id": "cxmt", "label": "CXMT", "type": "company",
             "aliases": ["CXMT", "长鑫", "长鑫存储"]},
            {"id": "ymtc", "label": "YMTC", "type": "company",
             "aliases": ["YMTC", "长江存储"]},
            {"id": "nvidia", "label": "NVIDIA", "type": "company",
             "aliases": ["NVIDIA", "英伟达"]},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        import yaml
        yaml.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def taxonomy(taxonomy_path):
    return Taxonomy(taxonomy_path)


@pytest.fixture
def repo_and_state():
    with tempfile.TemporaryDirectory() as d:
        repo = JsonlEventRepository(d, "storage")
        state = StateManager(d)
        yield repo, state


# Sample Agent EventThread — matches real format from event-threads.json
@pytest.fixture
def sample_thread():
    return {
        "id": "et-2026-001",
        "title": "CXMT科创板IPO与中国DRAM崛起",
        "canonical_question": "长鑫科技IPO如何影响DRAM竞争格局？",
        "status": "active",
        "priority": 1,
        "parent_cluster_ids": ["sc-2026-05-28-001"],
        "created": "2026-05-28",
        "last_updated": "2026-05-28",
        "timeline": [
            {
                "date": "2026-05-27",
                "event": "长鑫科技科创板IPO上会审议通过",
                "source_cluster": "sc-2026-05-28-001",
                "significance": "A股史上最大半导体IPO"
            },
            {
                "date": "2026-05-27",
                "event": "CXMT DDR5进入消费级渠道",
                "source_cluster": None,
                "significance": "DDR5产品获得第三方验证"
            },
        ],
        "current_assessment": "CXMT处于技术追赶到规模扩张的关键转折点。DDR5市占率快速攀升。",
        "open_questions": ["IPO最终定价？", "DDR5在更多品牌扩展？"],
        "watch_signals": ["CXMT IPO最终发行价", "新品牌采用CXMT DDR5"],
    }


@pytest.fixture
def minimal_thread():
    """Minimal thread with only required fields."""
    return {
        "id": "et-2026-099",
        "title": "Test Event",
        "status": "emerging",
        "priority": 3,
        "created": "2026-05-30",
        "last_updated": "2026-05-30",
    }


# ── Tests ──

class TestConvert:
    """Test _convert() — the core transformation logic."""

    def test_id_regeneration(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert event.id == "event-storage-0001"
        assert event.id != sample_thread["id"]

    def test_direct_field_mapping(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert event.title == "CXMT科创板IPO与中国DRAM崛起"
        assert event.canonical_question == "长鑫科技IPO如何影响DRAM竞争格局？"
        assert event.status == "active"
        assert event.priority == 1
        assert event.created == "2026-05-28"

    def test_timeline_conversion(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert len(event.timeline) == 2
        assert event.timeline[0].date == "2026-05-27"
        assert event.timeline[0].summary == "长鑫科技科创板IPO上会审议通过"
        assert event.timeline[0].update_type == "first_disclosure"
        assert event.timeline[0].confidence == "B"

    def test_topic_extraction(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        # Title has "IPO", "科创板"; assessment has "DDR5", "DRAM"
        assert "ipo" in event.topic_tags
        assert "ddr5" in event.topic_tags

    def test_entity_extraction(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert "cxmt" in event.entity_tags

    def test_occurred_at_from_timeline(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert event.occurred_at == "2026-05-27"

    def test_scale_refs_empty_before_ingest(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(sample_thread, "storage", state, taxonomy, "2026-05-28")
        assert event.scale_refs == []

    def test_minimal_thread(self, minimal_thread, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        event = _convert(minimal_thread, "storage", state, taxonomy, "2026-05-30")
        assert event.id == "event-storage-0001"
        assert event.title == "Test Event"
        assert event.timeline == []
        assert event.topic_tags == []
        assert event.entity_tags == []

    def test_sequence_increments(self, repo_and_state, taxonomy):
        from story_bridge import _convert
        repo, state = repo_and_state
        e1 = _convert({"title": "E1", "created": "2026-01-01", "last_updated": "2026-01-01"}, "storage", state, taxonomy, "2026-01-01")
        e2 = _convert({"title": "E2", "created": "2026-01-02", "last_updated": "2026-01-02"}, "storage", state, taxonomy, "2026-01-02")
        assert e1.id == "event-storage-0001"
        assert e2.id == "event-storage-0002"


class TestIngest:
    """Test ingest_event_thread() — full conversion + gate + persist."""

    def test_ingest_single(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state
        event = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert event is not None
        # Verify persisted
        assert repo.count() == 1
        retrieved = repo.get(event.id)
        assert retrieved is not None
        assert retrieved.title == "CXMT科创板IPO与中国DRAM崛起"

    def test_ingest_injects_scale_ref(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state
        event = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert len(event.scale_refs) == 1
        assert event.scale_refs[0].scale == "daily"
        assert event.scale_refs[0].briefing_id == "daily-2026-05-28"
        # Priority 1 → lead prominence
        assert event.scale_refs[0].prominence == "lead"

    def test_ingest_lower_priority_supporting(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state
        sample_thread["priority"] = 3
        event = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert event.scale_refs[0].prominence == "supporting"

    def test_ingest_no_briefing_id(self, sample_thread, repo_and_state, taxonomy):
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state
        event = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
        )
        assert event.scale_refs == []

    def test_ingest_gate_rejects_bad_event(self, repo_and_state, taxonomy):
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state
        bad_thread = {
            "title": "",  # Empty title → gate should reject
            "created": "2026-05-28",
            "last_updated": "2026-05-28",
        }
        event = ingest_event_thread(
            bad_thread, "storage", "2026-05-28", repo, state, taxonomy,
        )
        assert event is None
        assert repo.count() == 0

    # ── Idempotency tests ──

    def test_ingest_same_thread_id_is_idempotent(self, sample_thread, repo_and_state, taxonomy):
        """Re-ingesting the same thread_id should UPDATE, not create duplicate."""
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state

        # First ingestion
        e1 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert e1 is not None
        assert repo.count() == 1
        assert e1.thread_id == "et-2026-001"

        # Second ingestion — same thread_id
        e2 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert e2 is not None
        assert repo.count() == 1  # Still only one record!
        assert e2.id == e1.id    # Same event_id

    def test_ingest_new_briefing_id_appends_scale_ref(self, sample_thread, repo_and_state, taxonomy):
        """Re-ingesting with a different briefing_id appends a new ScaleRef."""
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state

        # First briefing
        e1 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert len(e1.scale_refs) == 1

        # Next day's briefing — same thread, different briefing_id
        sample_thread["last_updated"] = "2026-05-29"
        e2 = ingest_event_thread(
            sample_thread, "storage", "2026-05-29", repo, state, taxonomy,
            briefing_id="daily-2026-05-29",
        )
        assert len(e2.scale_refs) == 2
        assert e2.scale_refs[0].briefing_id == "daily-2026-05-28"
        assert e2.scale_refs[1].briefing_id == "daily-2026-05-29"
        assert repo.count() == 1  # Still one record

    def test_ingest_same_briefing_no_duplicate_scale_ref(self, sample_thread, repo_and_state, taxonomy):
        """Re-ingesting with the same briefing_id does NOT add duplicate ScaleRef."""
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state

        e1 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert len(e1.scale_refs) == 1

        e2 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )
        assert len(e2.scale_refs) == 1  # Not duplicated

    def test_ingest_updates_metadata_on_reeingest(self, sample_thread, repo_and_state, taxonomy):
        """Re-ingesting refreshes current_assessment, open_questions, etc."""
        from story_bridge import ingest_event_thread
        repo, state = repo_and_state

        e1 = ingest_event_thread(
            sample_thread, "storage", "2026-05-28", repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )

        # Simulate Agent updating the assessment
        sample_thread["current_assessment"] = "UPDATED: CXMT IPO finalized at ¥45/share"
        sample_thread["open_questions"] = ["New Q: Post-IPO volume ramp?"]
        sample_thread["status"] = "cooling"

        e2 = ingest_event_thread(
            sample_thread, "storage", "2026-05-29", repo, state, taxonomy,
            briefing_id="daily-2026-05-29",
        )
        assert e2.current_assessment == "UPDATED: CXMT IPO finalized at ¥45/share"
        assert "New Q: Post-IPO volume ramp?" in e2.open_questions
        assert e2.status == "cooling"
        assert e2.last_updated == "2026-05-29"


class TestBatch:
    """Test ingest_batch() — bulk ingestion."""

    def test_batch_ingest(self, repo_and_state, taxonomy):
        from story_bridge import ingest_batch
        repo, state = repo_and_state

        threads = [
            {
                "title": "Samsung HBM4 ships to NVIDIA",
                "canonical_question": "HBM4 market impact?",
                "status": "active", "priority": 1,
                "created": "2026-05-28", "last_updated": "2026-05-28",
                "timeline": [{"date": "2026-05-27", "event": "Samsung ships HBM4"}],
                "current_assessment": "Samsung leads HBM race",
            },
            {
                "title": "NAND prices stabilize",
                "canonical_question": "NAND pricing trend?",
                "status": "active", "priority": 2,
                "created": "2026-05-28", "last_updated": "2026-05-28",
                "current_assessment": "NAND market stabilizing",
            },
        ]

        stats = ingest_batch(threads, "storage", "2026-05-28", repo, state, taxonomy,
                            briefing_id="daily-2026-05-28")
        assert stats["ingested"] == 2
        assert stats["rejected"] == 0
        assert repo.count() == 2

    def test_batch_mixed(self, repo_and_state, taxonomy):
        from story_bridge import ingest_batch
        repo, state = repo_and_state

        threads = [
            {"title": "Good event", "canonical_question": "Q1?", "created": "2026-05-28", "last_updated": "2026-05-28"},
            {"title": "", "canonical_question": "", "created": "2026-05-28", "last_updated": "2026-05-28"},  # rejected
            {"title": "Another good", "canonical_question": "Q2?", "created": "2026-05-28", "last_updated": "2026-05-28"},
        ]

        stats = ingest_batch(threads, "storage", "2026-05-28", repo, state, taxonomy)
        assert stats["ingested"] == 2
        assert stats["rejected"] == 1
        assert repo.count() == 2
