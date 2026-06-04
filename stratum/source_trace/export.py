"""CSV exports for human-friendly SourceTrace review."""

from __future__ import annotations

import csv
import os
from typing import Any


def export_csvs(output_dir: str, outputs: dict[str, Any]) -> list[str]:
    """Export selected SourceTrace outputs as flat CSV files."""
    os.makedirs(output_dir, exist_ok=True)
    written = []
    mappings = {
        "source_quality": outputs.get("source_quality", []),
        "missed_signals": outputs.get("missed_signals", []),
        "policy_recommendations": outputs.get("policy_recommendations", []),
        "issues": outputs.get("issues", {}).get("issues", []),
        "funnel": outputs.get("funnel", {}).get("sources", []),
    }
    for name, rows in mappings.items():
        if not rows:
            continue
        path = os.path.join(output_dir, f"{name}.csv")
        _write_csv(path, rows)
        written.append(path)
    return written


def _write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    fields = sorted({field for row in rows for field in row.keys()})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _cell(row.get(field)) for field in fields})


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list, set, tuple)):
        return str(value)
    return value
