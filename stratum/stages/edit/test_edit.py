"""Tests for edit-stage output parsing and prompt data assembly."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from assembler import _build_data_section, _source_name, assemble
from edit import (
    _article_source_label,
    normalize_structured_data,
    repair_missing_source_lines,
    resolve_domain_title,
    should_write_event_threads,
    split_llm_output,
    structured_event_counts,
    strip_source_locale_tags,
)


def test_source_labels_strip_only_known_presentation_prefixes():
    article = {"url": "https://ww2.example.com/news"}
    assert _source_name(article) == "ww2.example.com"
    assert _article_source_label(article) == "ww2.example.com"

    mobile_article = {"url": "https://m.reuters.com/technology"}
    assert _source_name(mobile_article) == "reuters.com"
    assert _article_source_label(mobile_article) == "reuters.com"


def test_split_llm_output_accepts_valid_structured_data():
    response = """# Briefing

Body

---DATA---
{"causal_edges": [], "judgments": [{"id": "j1"}]}
"""
    briefing, data = split_llm_output(response)
    assert briefing == "# Briefing\n\nBody"
    assert data == {"causal_edges": [], "judgments": [{"id": "j1"}]}


def test_split_llm_output_ignores_invalid_structured_data():
    response = """# Briefing

Body

---DATA---
```json
{"causal_edges": [
```
"""
    briefing, data = split_llm_output(response)
    assert briefing == "# Briefing\n\nBody"
    assert data is None


def test_build_data_section_falls_back_to_source_domain():
    articles = [
        {
            "id": "a1",
            "title": "Samsung HBM4 update",
            "url": "https://www.reuters.com/technology/test",
            "source_domain": "reuters.com",
            "published_at": "2026-05-28T00:00:00+08:00",
            "snippet": "HBM4 sample update.",
        }
    ]
    clusters = {
        "clusters": [
            {
                "article_ids": ["a1"],
                "canonical_title": "Samsung HBM4 update",
                "confidence": 0.9,
            }
        ]
    }
    section = _build_data_section(articles, clusters, {}, "2026-05-28")
    assert "- reuters.com" in section
    assert "来源: reuters.com | 日期: 2026-05-28" in section
    assert "[en]" not in section


def test_daily_prompt_requests_threads_and_watch_signals():
    edit_dir = os.path.dirname(__file__)
    prompts_dir = os.path.join(edit_dir, "prompts")
    manifest_path = os.path.join(prompts_dir, "manifest.yaml")

    _system, user_prompt, output_cfg = assemble(
        manifest_path=manifest_path,
        prompts_dir=prompts_dir,
        timescale="daily",
        domain_cfg={"editorial": {}},
        domain_id="storage",
        run_date="2026-05-30",
        title="存储早报",
        articles=[{
            "id": "a1",
            "title": "Samsung HBM4 qualification advances",
            "source": "reuters.com",
            "published_at": "2026-05-30",
            "snippet": "Samsung HBM4 qualification advances with Nvidia.",
        }],
        clusters={"clusters": []},
        context={},
    )

    assert output_cfg["threads"]["enabled"] is True
    assert "请生成 threads 数组" in user_prompt
    assert "watch_signals" in user_prompt
    assert '"threads": [...]' in user_prompt
    assert '"causal_edges": [...]' in user_prompt
    assert '"judgments": [...]' in user_prompt


def test_strip_source_locale_tags_only_on_source_lines():
    md = """### Item

Body mentions [en] in prose.

*Digitimes [en], cnstock.com [zh-CN] · 2026年5月30日*
"""
    cleaned = strip_source_locale_tags(md)
    assert "*Digitimes, cnstock.com · 2026年5月30日*" in cleaned
    assert "Body mentions [en] in prose." in cleaned


def test_strip_source_locale_tags_handles_case_variants():
    md = "*Digitimes [EN], cnstock.com [zh-cn], example.jp [zh-Hans-CN] · 2026年5月30日*"

    cleaned = strip_source_locale_tags(md)

    assert cleaned == "*Digitimes, cnstock.com, example.jp · 2026年5月30日*"


def test_normalize_structured_data_renames_judgment_mechanism():
    data = {
        "judgments": [
            {
                "target_type": "event_pair",
                "target_thread_ids": ["et-2026-001", "et-2026-002"],
                "mechanism": "HBM demand lifts memory margins.",
                "confidence": "B",
                "expected_verification": "2026-12-31",
            }
        ]
    }
    normalized = normalize_structured_data(data)
    assert normalized["judgments"][0]["hypothesis"] == "HBM demand lifts memory margins."
    assert "mechanism" not in normalized["judgments"][0]


def test_normalize_structured_data_assigns_stable_thread_ids():
    data = {
        "threads": [
            {
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
            }
        ]
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    thread = normalized["threads"][0]
    assert thread["thread_id"].startswith("et-storage-20260530-")
    assert thread["id"] == thread["thread_id"]


def test_normalize_structured_data_keeps_existing_thread_id_from_id():
    data = {
        "threads": [
            {
                "id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
            }
        ]
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert normalized["threads"][0]["thread_id"] == "et-storage-0001"
    assert normalized["threads"][0]["id"] == "et-storage-0001"


def test_normalize_structured_data_coerces_structured_arrays():
    data = {
        "threads": {"title": "Single thread"},
        "causal_edges": "not-json-array",
        "judgments": {"mechanism": "HBM demand lifts margins."},
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert len(normalized["threads"]) == 1
    assert normalized["causal_edges"] == []
    assert normalized["judgments"] == [{"hypothesis": "HBM demand lifts margins."}]


def test_threads_only_structured_data_is_written():
    data = {
        "threads": [
            {
                "thread_id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 qualification"],
            }
        ],
        "causal_edges": [],
        "judgments": [],
    }

    assert should_write_event_threads(data)
    assert structured_event_counts(data) == {
        "threads": 1,
        "causal_edges": 0,
        "judgments": 0,
    }


def test_empty_structured_data_is_not_written():
    assert not should_write_event_threads({"threads": [], "causal_edges": [], "judgments": []})
    assert not should_write_event_threads(None)


def test_resolve_domain_title_prefers_config_override():
    title = resolve_domain_title(
        {"channels": {"storage": {"title": "Override Briefing"}}},
        {"domain": {"title": "存储早报"}},
        "storage",
    )
    assert title == "Override Briefing"


def test_resolve_domain_title_falls_back_to_domain_yaml():
    title = resolve_domain_title({}, {"domain": {"title": "存储早报"}}, "storage")
    assert title == "存储早报"


def test_repair_missing_source_lines_adds_clear_article_match():
    md = """# 存储早报

### Samsung HBM4 sample update

Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30T08:00:00+08:00",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert "*reuters.com · 2026年5月30日*" in repaired


def test_repair_missing_source_lines_skips_structural_sections():
    md = """### 今日要点

Samsung HBM4 samples moved forward for Nvidia qualification.

---

### 关注

- Samsung HBM4 samples moved forward for Nvidia qualification.

---

### 反向信号

- Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30T08:00:00+08:00",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert "reuters.com" not in repaired


def test_repair_missing_source_lines_keeps_existing_source_line():
    md = """### Samsung HBM4 sample update

Body.

*Reuters · 2026年5月30日*
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert repaired.count("Reuters") == 1
    assert "reuters.com" not in repaired


def test_repair_missing_source_lines_ignores_weak_match():
    md = """### Random packaging rumor

This paragraph has no overlap with the article pool.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert "reuters.com" not in repaired


def test_repaired_source_line_passes_validate_item():
    from stratum.stages.validate.validate import parse_markdown, validate_item
    import tempfile

    md = """### Samsung HBM4 sample update

Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]
    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    with tempfile.NamedTemporaryFile("w+", suffix=".md") as f:
        f.write(repaired)
        f.flush()
        items = parse_markdown(f.name)

    assert len(items) == 1
    assert validate_item(items[0], articles, "2026-05-30", {}) == []


def test_call_llm_sends_payload_via_stdin(monkeypatch):
    import json
    import subprocess
    import llm_client

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"choices": [{"message": {"content": "ok"}}]}),
            stderr="",
        )

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    result = llm_client.call_llm(
        "system prompt",
        "user prompt",
        {"api_key": "key", "model": "model", "endpoint": "https://example.com"},
    )

    assert result == "ok"
    assert "--data-binary" in captured["cmd"]
    assert "@-" in captured["cmd"]
    assert "system prompt" in captured["input"]
    assert "user prompt" in captured["input"]
    assert "system prompt" not in captured["cmd"]
    assert "user prompt" not in captured["cmd"]
