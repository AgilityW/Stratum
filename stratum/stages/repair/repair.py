#!/usr/bin/env python3
"""repair.py — post-validate briefing repair stage."""

from __future__ import annotations

import argparse
import json
import sys

try:
    from stratum.stages.edit.validate_repair import (
        load_validate_report,
        repair_briefing_from_validate_report,
    )
    from stratum.stages.validate import load_articles, load_domain_config, resolve_date_window
except ImportError:  # pragma: no cover
    from stratum.stages.edit.validate_repair import (
        load_validate_report,
        repair_briefing_from_validate_report,
    )
    from stratum.stages.validate.validate import load_articles, load_domain_config, resolve_date_window


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair briefing from validate report")
    parser.add_argument("--md", required=True, help="Briefing markdown file to rewrite in place")
    parser.add_argument("--articles", required=True, help="Articles JSONL file")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    parser.add_argument("--validate-report", required=True, help="Structured validate report JSON")
    parser.add_argument("--output-report", required=True, help="Output repair_report.json path")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    source_aliases = pipeline_config.get("source_aliases", {})
    max_future_days, stale_days = resolve_date_window(pipeline_config)
    articles = load_articles(args.articles)
    validate_report = load_validate_report(args.validate_report)
    with open(args.md) as f:
        markdown = f.read()

    repaired_markdown, repair_report = repair_briefing_from_validate_report(
        markdown,
        articles,
        validate_report,
        args.date,
        source_aliases,
        max_future_days=max_future_days,
        stale_days=stale_days,
    )

    with open(args.md, "w") as f:
        f.write(repaired_markdown)
    with open(args.output_report, "w") as f:
        json.dump(repair_report, f, ensure_ascii=False, indent=2)

    print(json.dumps(repair_report, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
