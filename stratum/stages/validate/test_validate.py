"""Tests for validate stage — briefing factuality gate."""
import pytest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.validate.validate import (
    parse_markdown, validate_item, load_domain_config
)


MOCK_SOURCE_ALIASES = {
    "reuters": "reuters.com",
    "bloomberg": "bloomberg.com",
    "trendforce": "trendforce.com",
    "digitimes": "digitimes.com",
    "新浪财经": "finance.sina.com.cn",
    "财新": "caixin.com",
}


SAMPLE_BRIEFING = """# 存储早报
## 2026年5月28日 · 周四

今日存储产业动态...

---

### Samsung ships HBM4 to NVIDIA
Samsung Electronics announced HBM4 mass production.

*Reuters · 2026年5月28日*

### Memory prices rise in Q2
DRAM and NAND prices continue upward trend.

*Trendforce, Bloomberg · 2026年5月28日*

---

### 关注
- Follow HBM4 certification progress

### 反向信号
- If hyperscaler capex drops sharply

---

*由 AI Agent 自动生成 · 2026年5月28日*
"""


class TestParseMarkdown:
    def test_parses_items(self):
        items = parse_markdown_from_str(SAMPLE_BRIEFING)
        assert len(items) == 2
        assert items[0]["title"] == "Samsung ships HBM4 to NVIDIA"
        assert "Reuters" in items[0]["sources"]
        assert "2026年5月28日" in items[0]["date"]

    def test_skips_section_headers(self):
        items = parse_markdown_from_str(SAMPLE_BRIEFING)
        titles = [i["title"] for i in items]
        assert "关注" not in titles
        assert "反向信号" not in titles


class TestValidateItem:
    def test_valid_source(self):
        articles = [
            {"source": "reuters.com", "id": "a1", "title": "Samsung HBM4"},
            {"source": "trendforce.com", "id": "a2", "title": "Memory prices"},
            {"source": "bloomberg.com", "id": "a3", "title": "DRAM prices"},
        ]
        item = {
            "title": "Samsung HBM4",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert len(violations) == 0

    def test_missing_source(self):
        articles = [
            {"source": "reuters.com", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["UnknownSource"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE" in v for v in violations)

    def test_stale_date(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月20日",  # 8 days old
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("DATE" in v for v in violations)

    def test_no_sources_violation(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {"title": "Test", "sources": [], "date": "2026年5月28日", "body": []}
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE" in v for v in violations)


def parse_markdown_from_str(content: str):
    """Helper: parse markdown from string instead of file."""
    items = []
    current_item = None

    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('### ') and '今日要点' not in line and '关注' not in line and '反向信号' not in line:
            if current_item:
                items.append(current_item)
            current_item = {
                'title': line.replace('### ', '').strip(),
                'body': [], 'sources': [], 'date': None,
            }
        elif current_item and line.startswith('*') and '·' in line:
            source_line = line.strip('* ')
            parts = source_line.split('·')
            if len(parts) >= 2:
                sources_part = parts[0].strip()
                date_part = parts[-1].strip()
                current_item['sources'] = [s.strip() for s in sources_part.split(',')]
                current_item['date'] = date_part
        elif current_item and line and not line.startswith('#'):
            current_item['body'].append(line)

    if current_item:
        items.append(current_item)
    return items
