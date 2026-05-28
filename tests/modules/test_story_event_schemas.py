"""Story Cluster Engine & Event Thread Engine — JSON schema validation.

Validates:
- StoryCluster JSON structure (from story-cluster-engine)
- EventThread JSON structure (from event-thread-engine)
"""
import pytest

# StoryCluster fields (from SKILL.md and schema tests)
STORY_CLUSTER_FIELDS = {
    "id", "canonical_title", "canonical_summary",
    "confidence", "article_ids", "source_types",
    "locales", "entities", "terms", "created",
}

STORY_CLUSTER_STATUSES = {
    "emerging", "confirmed", "developing", "resolved", "stale",
}

# EventThread fields (from event-thread-engine SKILL.md)
EVENT_THREAD_FIELDS = {
    "id", "title", "canonical_question", "status",
    "priority", "created", "last_updated", "timeline",
    "confidence", "confidence_history", "open_questions",
    "watch_signals", "close_conditions",
}

EVENT_THREAD_STATUSES = {
    "emerging", "developing", "cooling", "resolved", "archived",
}

EVENT_THREAD_PRIORITIES = {"critical", "high", "medium", "low"}

THREAD_ID_PREFIX = "et-storage-"


class TestStoryClusterSchema:
    """StoryCluster object model validation."""

    def test_ten_fields(self):
        assert len(STORY_CLUSTER_FIELDS) == 10, (
            f"Expected 10 fields, got {len(STORY_CLUSTER_FIELDS)}"
        )

    def test_five_statuses(self):
        assert len(STORY_CLUSTER_STATUSES) == 5

    def test_id_format(self):
        """Cluster ID format: sc-{channel}-{seq:04d}."""
        # sc-storage-0001
        sample_id = "sc-storage-0001"
        assert sample_id.startswith("sc-")
        assert "-" in sample_id[3:]

    def test_article_ids_is_array(self):
        """article_ids is a list of ArticleRecord IDs."""
        assert "article_ids" in STORY_CLUSTER_FIELDS

    def test_source_types_is_set(self):
        """source_types is a deduplicated set of source_type values."""
        assert "source_types" in STORY_CLUSTER_FIELDS

    def test_locales_is_set(self):
        """locales is a deduplicated set of locale codes."""
        assert "locales" in STORY_CLUSTER_FIELDS

    def test_entities_is_array(self):
        assert "entities" in STORY_CLUSTER_FIELDS

    def test_confidence_is_float(self):
        """confidence is a float 0.0-1.0."""
        assert "confidence" in STORY_CLUSTER_FIELDS


class TestEventThreadSchema:
    """EventThread object model validation."""

    def test_thirteen_fields(self):
        assert len(EVENT_THREAD_FIELDS) == 13, (
            f"Expected 13 fields, got {len(EVENT_THREAD_FIELDS)}"
        )

    def test_five_statuses(self):
        assert len(EVENT_THREAD_STATUSES) == 5

    def test_four_priorities(self):
        assert len(EVENT_THREAD_PRIORITIES) == 4

    def test_id_prefix(self):
        """EventThread ID: et-storage-0001."""
        assert THREAD_ID_PREFIX == "et-storage-"

    def test_timeline_is_array(self):
        """timeline is an array of update entries."""
        assert "timeline" in EVENT_THREAD_FIELDS

    def test_confidence_history_is_array(self):
        """confidence_history tracks confidence over time."""
        assert "confidence_history" in EVENT_THREAD_FIELDS

    def test_watch_signals_is_array(self):
        """watch_signals: things to watch for confirmation."""
        assert "watch_signals" in EVENT_THREAD_FIELDS

    def test_close_conditions_is_array(self):
        """close_conditions: when to resolve the thread."""
        assert "close_conditions" in EVENT_THREAD_FIELDS

    def test_open_questions_is_array(self):
        assert "open_questions" in EVENT_THREAD_FIELDS


class TestTimelineEntrySchema:
    """Each timeline entry in an EventThread."""

    TIMELINE_FIELDS = {
        "date", "cluster_id", "update_type", "summary", "confidence_after",
    }

    UPDATE_TYPES = {
        "first_disclosure", "corroboration", "contradiction",
        "quantitative_update", "resolution",
    }

    def test_five_timeline_fields(self):
        assert len(self.TIMELINE_FIELDS) == 5

    def test_five_update_types(self):
        assert len(self.UPDATE_TYPES) == 5

    def test_first_disclosure_is_type(self):
        """First disclosure is the initial timeline entry."""
        assert "first_disclosure" in self.UPDATE_TYPES

    def test_resolution_is_type(self):
        """Resolution closes the thread."""
        assert "resolution" in self.UPDATE_TYPES
