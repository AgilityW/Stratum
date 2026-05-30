"""Tests for edit-stage output parsing and prompt data assembly."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from assembler import _build_data_section, _source_name, assemble
from edit import (
    _article_source_label,
    item_count_within_budget,
    markdown_news_titles,
    normalize_structured_data,
    normalize_edge_signal_headings,
    repair_source_line_dates,
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


def test_build_data_section_respects_prompt_budget():
    articles = []
    for index in range(5):
        articles.append({
            "id": f"a{index}",
            "title": f"Samsung HBM4 update {index}",
            "url": f"https://example.com/{index}",
            "source": "example.com",
            "source_type": "media",
            "published_at": "2026-05-30T00:00:00+08:00",
            "snippet": f"HBM4 update {index}",
        })
    clusters = {
        "clusters": [{
            "id": "sc-1",
            "article_ids": [a["id"] for a in articles],
            "canonical_title": "Samsung HBM4 update",
            "confidence": "high",
        }]
    }

    section = _build_data_section(
        articles,
        clusters,
        {},
        "2026-05-30",
        {"max_articles_per_cluster": 2, "prompt_max_chars": 10000},
    )

    assert "本 prompt 选入 2 篇" in section
    assert "省略 3 篇" in section
    assert "Samsung HBM4 update 0" in section
    assert "Samsung HBM4 update 2" not in section


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


def test_daily_prompt_instructs_edge_signal_category():
    edit_dir = os.path.dirname(__file__)
    prompts_dir = os.path.join(edit_dir, "prompts")
    manifest_path = os.path.join(prompts_dir, "manifest.yaml")

    system_prompt, user_prompt, _output_cfg = assemble(
        manifest_path=manifest_path,
        prompts_dir=prompts_dir,
        timescale="daily",
        domain_cfg={"editorial": {}},
        domain_id="storage",
        run_date="2026-05-30",
        title="存储早报",
        articles=[{
            "id": "a1",
            "title": "Glass storage reaches small scale production",
            "source": "example.com",
            "published_at": "2026-05-30",
            "snippet": "Glass storage is a weak but observable storage signal.",
        }],
        clusters={"clusters": []},
        context={},
    )

    combined = system_prompt + user_prompt
    assert "【边缘信号】" in combined
    assert "20-30 条" in combined
    assert "16-18 条" in combined
    assert "5-8 条" in combined
    assert "Anthropic" in combined
    assert "为什么值得观察" in combined


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


def test_normalize_structured_data_rewrites_cluster_ids_to_thread_ids():
    data = {
        "threads": [
            {"thread_id": "sc-storage-0001", "title": "Samsung HBM4"},
            {"thread_id": "sc-storage-0002", "title": "DRAM prices"},
        ],
        "causal_edges": [
            {
                "cause_thread_id": "sc-storage-0001",
                "effect_thread_id": "sc-storage-0002",
                "mechanism": "HBM capacity displaces commodity DRAM.",
                "confidence": "B",
            }
        ],
        "judgments": [
            {
                "target_type": "event_pair",
                "target_thread_ids": ["sc-storage-0001", "sc-storage-0002"],
                "hypothesis": "HBM capacity pressure keeps DRAM prices elevated.",
                "confidence": "B",
                "expected_verification": "2026-12-31",
            }
        ],
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    rewritten_ids = [thread["thread_id"] for thread in normalized["threads"]]
    assert all(thread_id.startswith("et-storage-20260530-") for thread_id in rewritten_ids)
    assert normalized["causal_edges"][0]["cause_thread_id"] == rewritten_ids[0]
    assert normalized["causal_edges"][0]["effect_thread_id"] == rewritten_ids[1]
    assert normalized["judgments"][0]["target_thread_ids"] == rewritten_ids


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


def test_normalize_structured_data_drops_incomplete_causal_edges():
    data = {
        "threads": [{"thread_id": "et-storage-0001", "title": "DRAM prices"}],
        "causal_edges": [
            {
                "cause_thread_id": "et-storage-0001",
                "effect_thread_id": None,
                "mechanism": "Demand destruction",
                "confidence": "B",
            },
            {
                "cause_thread_id": "et-storage-0001",
                "effect_thread_id": "et-storage-0002",
                "mechanism": "Capacity displacement",
                "confidence": "B",
            },
        ],
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert len(normalized["causal_edges"]) == 1
    assert normalized["causal_edges"][0]["effect_thread_id"] == "et-storage-0002"


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


def test_normalize_edge_signal_headings_prefixes_weak_titles():
    md = """### Anthropic investment update

Body.

---

### 三星HBM4E样品出货

Body.
"""

    normalized = normalize_edge_signal_headings(md)

    assert "### 【边缘信号】Anthropic investment update" in normalized
    assert "### 三星HBM4E样品出货" in normalized


def test_item_count_within_budget_checks_min_and_max():
    md = """### 今日要点

Summary.

### Item 1

Body.

### 【边缘信号】Item 2

Body.
"""

    assert markdown_news_titles(md) == ["Item 1", "【边缘信号】Item 2"]
    ok, detail = item_count_within_budget(md, {"_budget": {"min_items": 2, "max_items": 3}})
    assert ok, detail
    ok, detail = item_count_within_budget(md, {"_budget": {"min_items": 3, "max_items": 4}})
    assert not ok
    assert "minimum" in detail


def test_item_count_within_budget_checks_main_and_edge_ranges():
    md = """### 今日要点

Summary.

### Item 1

Body.

### Item 2

Body.

### 【边缘信号】Item 3

Body.

### 【边缘信号】Item 4

Body.
"""

    budget = {
        "_budget": {
            "min_items": 4,
            "max_items": 6,
            "main_min_items": 2,
            "main_max_items": 3,
            "edge_min_items": 2,
            "edge_max_items": 3,
        },
    }
    ok, detail = item_count_within_budget(md, budget)
    assert ok, detail

    low_edge_budget = {"_budget": dict(budget["_budget"], edge_min_items=3)}
    ok, detail = item_count_within_budget(md, low_edge_budget)
    assert not ok
    assert "edge minimum" in detail

    low_main_budget = {"_budget": dict(budget["_budget"], main_min_items=3)}
    ok, detail = item_count_within_budget(md, low_main_budget)
    assert not ok
    assert "main minimum" in detail


def test_repair_source_line_dates_uses_matching_article_date():
    md = """### SK hynix iHBM update

SK hynix iHBM thermal solution for HBM5.

*trendforce.com · 2026年5月26日*
"""
    articles = [
        {
            "title": "SK hynix iHBM thermal solution",
            "snippet": "SK hynix iHBM thermal solution for HBM5",
            "source": "trendforce.com",
            "published_at": "2026-05-30T00:00:00+08:00",
        }
    ]

    repaired = repair_source_line_dates(md, articles, "2026-05-30")

    assert "*trendforce.com · 2026年5月30日*" in repaired


def test_repair_source_line_dates_filters_unsupported_sources():
    md = """### Micron India facility ramps production

Micron's India packaging facility started volume production for memory chips.

*v.daum.net, investors.micron.com · 2026年5月30日*
"""
    articles = [
        {
            "title": "Samsung expands memory capacity in Korea",
            "snippet": "Samsung and SK hynix plan additional DRAM cleanroom investments.",
            "source": "v.daum.net",
            "published_at": "2026-05-30",
        },
        {
            "title": "Micron India packaging facility starts volume production",
            "snippet": "Micron said its India memory packaging facility ramped production.",
            "source": "investors.micron.com",
            "published_at": "2026-05-30",
        },
    ]

    repaired = repair_source_line_dates(md, articles, "2026-05-30")

    assert "*investors.micron.com · 2026年5月30日*" in repaired
    assert "v.daum.net" not in repaired


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
    assert "-sS" in captured["cmd"]
    assert "--max-time" in captured["cmd"]


def test_call_llm_reports_curl_failure(monkeypatch):
    import subprocess
    import llm_client

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 56, stdout="", stderr="connection reset")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    try:
        llm_client.call_llm("system", "user", {"api_key": "key", "endpoint": "https://example.com"})
    except RuntimeError as exc:
        assert "curl exited 56" in str(exc)
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_call_llm_reports_empty_content(monkeypatch):
    import json
    import subprocess
    import llm_client

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 1},
            }) + "\nHTTP_STATUS:200\n",
            stderr="",
        )

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    try:
        llm_client.call_llm("system", "user", {"api_key": "key", "endpoint": "https://example.com"})
    except RuntimeError as exc:
        assert "empty content" in str(exc)
        assert "finish_reason=length" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
