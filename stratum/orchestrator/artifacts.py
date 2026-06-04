"""Run artifact path cleanup helpers."""

from __future__ import annotations

import os
import sys

from stratum.contracts.pipeline_artifacts import (
    LEGACY_RAW_ALIASES,
    LEGACY_WATCHLIST_SIDECAR_ALIASES,
)


def remove_legacy_briefing_artifacts(paths: dict) -> None:
    """Remove stale briefing.* artifacts now that canonical names are used."""
    data_dir = paths.get("data_dir", "")
    if not data_dir:
        return
    canonical_paths = {
        os.path.abspath(paths.get("briefing_md", "")),
        os.path.abspath(paths.get("briefing_html", "")),
        os.path.abspath(paths.get("briefing_pdf", "")),
    }
    for legacy_name in ("briefing.md", "briefing.html", "briefing.pdf"):
        legacy_path = os.path.abspath(os.path.join(data_dir, legacy_name))
        if legacy_path in canonical_paths or not os.path.exists(legacy_path):
            continue
        try:
            os.remove(legacy_path)
        except OSError as exc:
            print(f"⚠️  Could not remove legacy artifact {legacy_path}: {exc}", file=sys.stderr)


def clear_delivery_artifacts(paths: dict) -> None:
    """Remove canonical delivery artifacts before a fresh Edit attempt."""
    for key in ("briefing_md", "briefing_html", "briefing_pdf"):
        path = paths.get(key)
        if not path or not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError as exc:
            print(f"⚠️  Could not remove stale delivery artifact {path}: {exc}", file=sys.stderr)


def remove_legacy_raw_artifacts(paths: dict) -> None:
    """Remove stale raw-data aliases and legacy collector sidecars."""
    data_dir = paths.get("data_dir", "")
    if not data_dir:
        return
    canonical_raw = os.path.abspath(paths.get("raw", ""))
    for legacy_name in LEGACY_RAW_ALIASES:
        legacy_path = os.path.abspath(os.path.join(data_dir, legacy_name))
        if legacy_path == canonical_raw or not os.path.exists(legacy_path):
            continue
        try:
            os.remove(legacy_path)
        except OSError as exc:
            print(f"⚠️  Could not remove legacy raw artifact {legacy_path}: {exc}", file=sys.stderr)
    for legacy_name in LEGACY_WATCHLIST_SIDECAR_ALIASES:
        legacy_path = os.path.abspath(os.path.join(data_dir, legacy_name))
        if not os.path.exists(legacy_path):
            continue
        try:
            os.remove(legacy_path)
        except OSError as exc:
            print(f"⚠️  Could not remove legacy watchlist artifact {legacy_path}: {exc}", file=sys.stderr)
