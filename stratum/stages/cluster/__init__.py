"""Cluster stage package.

Cluster keeps CLI/file handoff logic in `cluster.py` and clustering algorithms
in `story_clusterer.py`. Internal imports should prefer package-relative paths.
"""

from .cluster import build_cluster_object, extract_domain_id
from .story_clusterer import (
    ClusterConfidenceScorer,
    StoryClusterer,
    cluster_articles,
    jaccard_similarity,
    weighted_overlap_similarity,
)

__all__ = [
    "ClusterConfidenceScorer",
    "StoryClusterer",
    "build_cluster_object",
    "cluster_articles",
    "extract_domain_id",
    "jaccard_similarity",
    "weighted_overlap_similarity",
]
