#!/usr/bin/env python3
"""edit.py — Agent Edit: LLM generates validated briefing.md from articles + clusters.

Thin orchestration layer. Prompt assembly delegated to assembler.py.
LLM call delegated to llm_client.py.

Input:  verified articles (JSONL), clusters (JSON), story context (JSON),
        domain.yaml, config.yaml, manifest + prompt fragments.
Output: briefing.md (+ optional event-threads.json for causal_edges/judgments).

Usage:
    python3 edit.py --domain storage --date 2026-05-29 --timescale daily \\
        --articles articles.jsonl --clusters clusters.json \\
        --context story_context.json --config config.yaml \\
        --output briefing.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime

# ── Internal imports ──
_EDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _EDIT_DIR)
from assembler import assemble, _format_cn_date
from llm_client import call_llm

CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load_config_with_env(config_path: str) -> dict:
    """Load config.yaml, resolving ${VAR} and reading .env from config's directory."""
    config_dir = os.path.dirname(os.path.abspath(config_path))
    env_path = os.path.join(config_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val

    with open(config_path) as f:
        raw = f.read()
    for match in re.finditer(r'\$\{(\w+)\}', raw):
        var_name = match.group(1)
        env_val = os.environ.get(var_name, "")
        raw = raw.replace(match.group(0), env_val)
    return yaml.safe_load(raw)


def load_articles(path: str) -> list[dict]:
    """Load articles from JSONL file."""
    articles = []
    with open(path) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))
    return articles


def load_domain_cfg(domain_config_path: str) -> dict:
    """Load full domain.yaml."""
    with open(domain_config_path) as f:
        return yaml.safe_load(f)


def split_llm_output(response: str) -> tuple[str, dict | None]:
    """Split LLM response into briefing markdown and structured data.

    Expects: markdown\\n---DATA---\\n{json}
    Returns: (briefing_md, structured_data_or_None)
    """
    marker = "---DATA---"
    if marker in response:
        parts = response.split(marker, 1)
        briefing = parts[0].strip()
        try:
            data = json.loads(parts[1].strip())
        except json.JSONDecodeError:
            # Graceful fallback: try to extract JSON block
            match = re.search(r'\{[\s\S]*\}', parts[1])
            data = json.loads(match.group(0)) if match else None
        return briefing, data
    return response.strip(), None


def main():
    parser = argparse.ArgumentParser(description="LLM-driven briefing generation")
    parser.add_argument("--domain", "-d", required=True, help="Domain ID (e.g. 'storage')")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--timescale", "-t", default="daily",
                        choices=["daily", "weekly", "monthly", "quarterly", "yearly"],
                        help="Timescale (default: daily)")
    parser.add_argument("--articles", required=True, help="Path to articles.jsonl")
    parser.add_argument("--clusters", required=True, help="Path to clusters.json")
    parser.add_argument("--context", required=True, help="Path to story_context.json")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--output", "-o", required=True, help="Output briefing.md path")
    args = parser.parse_args()

    # ── Load config and resolve API keys ──
    config = load_config_with_env(args.config)
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("api_key"):
        print("❌ No LLM API key configured. Add 'llm.api_key' to config.yaml")
        sys.exit(1)

    # ── Load data ──
    articles = load_articles(args.articles)
    with open(args.clusters) as f:
        clusters = json.load(f)
    context = {}
    if os.path.exists(args.context):
        with open(args.context) as f:
            context = json.load(f)

    # ── Resolve title from config ──
    channels = config.get("channels", {})
    channel_title = channels.get(args.domain, {}).get("title", "")
    title = channel_title or config.get("domain", {}).get("title", "")

    # ── Load domain config ──
    # Derive domain.yaml path from config or convention
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    domain_config_path = os.path.join(project_root, "domains", args.domain, "domain.yaml")
    domain_cfg = load_domain_cfg(domain_config_path)

    # ── Assemble prompt via assembler ──
    prompts_dir = os.path.join(_EDIT_DIR, "prompts")
    manifest_path = os.path.join(prompts_dir, "manifest.yaml")

    print(f"\n📝 Assembling prompt (timescale={args.timescale})...", file=sys.stderr)
    system_prompt, user_prompt, output_cfg = assemble(
        manifest_path=manifest_path,
        prompts_dir=prompts_dir,
        timescale=args.timescale,
        domain_cfg=domain_cfg,
        domain_id=args.domain,
        run_date=args.date,
        title=title or f"{args.domain}早报",
        articles=articles,
        clusters=clusters,
        context=context,
    )

    print(f"   System prompt: {len(system_prompt)} chars", file=sys.stderr)
    print(f"   User prompt:   {len(user_prompt)} chars", file=sys.stderr)
    print(f"   Model: {llm_cfg.get('model', 'deepseek-v4-pro')}", file=sys.stderr)
    print(f"   Title: {title or '(from domain)'}", file=sys.stderr)

    # ── Call LLM ──
    print(f"   Calling LLM...", file=sys.stderr)
    try:
        response = call_llm(system_prompt, user_prompt, llm_cfg)
    except Exception as e:
        print(f"❌ LLM call failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Split output ──
    briefing, structured_data = split_llm_output(response)

    # ── Apply header ──
    if title:
        cn_date = _format_cn_date(args.date)
        header = f"# {title}\n## {cn_date}\n\n"
        if not briefing.startswith("# "):
            briefing = header + briefing

    # ── Write briefing.md ──
    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w") as f:
        f.write(briefing)
    print(f"✅ Briefing written: {args.output} ({len(briefing)} chars)", file=sys.stderr)

    # ── Write event-threads.json (if structured output) ──
    if structured_data:
        has_edges = bool(structured_data.get("causal_edges"))
        has_judgments = bool(structured_data.get("judgments"))
        if has_edges or has_judgments:
            event_threads_path = os.path.join(output_dir, "event-threads.json")
            with open(event_threads_path, "w") as f:
                json.dump(structured_data, f, ensure_ascii=False, indent=2)
            n_edges = len(structured_data.get("causal_edges", []))
            n_judgments = len(structured_data.get("judgments", []))
            print(f"✅ Event threads written: {event_threads_path} "
                  f"({n_edges} causal_edges, {n_judgments} judgments)", file=sys.stderr)


if __name__ == "__main__":
    main()
