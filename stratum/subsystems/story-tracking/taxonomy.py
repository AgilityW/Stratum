"""Taxonomy loader — reads domain taxonomy.yaml, normalizes tags.

Domain-specific: loads from domains/{domain_id}/taxonomy.yaml.
The agent uses this to normalize event tags before storage.
"""

import os
import yaml
from typing import Optional


class Taxonomy:
    """Controlled vocabulary for a domain.

    Loads from a YAML file and provides:
    - normalize(tag) → canonical ID or original tag
    - expand(tag) → all aliases for a canonical ID
    - exists(tag) → is this a known term?
    """

    def __init__(self, yaml_path: str):
        self._path = yaml_path
        self._topics: dict = {}       # alias → id
        self._topic_ids: set = set()
        self._entities: dict = {}     # alias → id
        self._entity_ids: set = set()
        self._topic_tree: dict = {}   # id → parent_id
        self._entity_tree: dict = {}  # id → parent_id

        if os.path.exists(yaml_path):
            self._load()

    def _load(self):
        with open(self._path, "r") as f:
            data = yaml.safe_load(f) or {}

        for topic in data.get("topics", []):
            tid = topic["id"]
            self._topic_ids.add(tid)
            if topic.get("parent"):
                self._topic_tree[tid] = topic["parent"]
            for alias in [tid] + topic.get("aliases", []):
                self._topics[alias.lower()] = tid

        for entity in data.get("entities", []):
            eid = entity["id"]
            self._entity_ids.add(eid)
            if entity.get("parent"):
                self._entity_tree[eid] = entity["parent"]
            for alias in [eid] + entity.get("aliases", []):
                self._entities[alias.lower()] = eid

    # ── Normalization ──

    def normalize_topic(self, tag: str) -> str:
        """Return canonical topic ID, or original tag if unknown."""
        return self._topics.get(tag.lower(), tag)

    def normalize_entity(self, tag: str) -> str:
        """Return canonical entity ID, or original tag if unknown."""
        return self._entities.get(tag.lower(), tag)

    def normalize_event_tags(self, event) -> None:
        """Normalize topic_tags and entity_tags in-place on an EventRecord."""
        event.topic_tags = [self.normalize_topic(t) for t in event.topic_tags]
        event.entity_tags = [self.normalize_entity(e) for e in event.entity_tags]

    # ── Queries ──

    def is_known_topic(self, tag: str) -> bool:
        return tag.lower() in self._topics

    def is_known_entity(self, tag: str) -> bool:
        return tag.lower() in self._entities

    def topic_parent(self, topic_id: str) -> Optional[str]:
        return self._topic_tree.get(topic_id)

    def entity_parent(self, entity_id: str) -> Optional[str]:
        return self._entity_tree.get(entity_id)

    def topic_ancestors(self, topic_id: str) -> list[str]:
        """All ancestors from immediate parent to root."""
        ancestors = []
        current = self._topic_tree.get(topic_id)
        while current:
            ancestors.append(current)
            current = self._topic_tree.get(current)
        return ancestors

    # ── Unknown Tag Detection ──

    def unknown_topics(self, tags: list[str]) -> list[str]:
        """Tags not in the taxonomy — agent should propose them for addition."""
        return [t for t in tags if not self.is_known_topic(t)]

    def unknown_entities(self, tags: list[str]) -> list[str]:
        return [t for t in tags if not self.is_known_entity(t)]


# ── Convenience Factory ──

def load_taxonomy(project_root: str, domain_id: str) -> Taxonomy:
    """Load taxonomy from the standard domain config path."""
    path = os.path.join(project_root, "domains", domain_id, "taxonomy.yaml")
    return Taxonomy(path)
