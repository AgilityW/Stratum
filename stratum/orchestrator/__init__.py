"""Orchestrator package for Stratum runtime composition.

This package keeps CLI entrypoints thin:

- `pipeline.py` owns top-level argument parsing and daily/higher-scale dispatch.
- `run_context.py` owns shared runtime path/stage/manifest helpers.
- `watchlist_runtime.py`, `story_runtime.py`, and `db_runtime.py` own
  best-effort helper surfaces around acquisition feedback, story context, and
  SQLite ingest.

Import concrete helpers from those modules rather than re-implementing runtime
logic in new orchestration call sites.
"""

from .run_context import resolve_paths, resolve_runtime_dirs

__all__ = ["resolve_paths", "resolve_runtime_dirs"]
