"""Tests for render stage."""
import json
import os
import tempfile
import pytest
from pathlib import Path

# Import render functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from render import esc, detect_tags, load_render_tags, convert


class TestEsc:
    """HTML escaping and markdown→HTML conversion helpers."""

    def test_esc_ampersand(self):
        assert esc("A & B") == "A &amp; B"

    def test_esc_angle_brackets(self):
        assert esc("<script>") == "&lt;script&gt;"

    def test_esc_quote(self):
        assert esc('say "hello"') == 'say &quot;hello&quot;'

    def test_esc_bold_markdown(self):
        assert esc("**hello**") == "<strong>hello</strong>"

    def test_esc_plain_text(self):
        assert esc("hello world") == "hello world"


class TestDetectTags:
    """Tag detection reads from domain config — no hardcoded keywords."""

    def test_empty_config(self):
        tags = detect_tags("SK hynix announces HBM4", "New product launch", {})
        assert tags == []

    def test_detects_new_tag(self):
        config = {
            "new": {"label": "new", "class": "tag-new",
                    "keywords": ["announce", "launch", "推出"]},
        }
        tags = detect_tags("SK hynix announces HBM4", "", config)
        assert ("new", "tag-new") in tags

    def test_detects_tech_tag(self):
        config = {
            "tech": {"label": "tech", "class": "tag-tech",
                     "keywords": ["nm", "layer", "制程"]},
        }
        tags = detect_tags("", "TSMC 3nm process node", config)
        assert ("tech", "tag-tech") in tags

    def test_detects_multiple_tags(self):
        config = {
            "new": {"label": "new", "class": "tag-new",
                    "keywords": ["announce"]},
            "price": {"label": "price", "class": "tag-price",
                      "keywords": ["price", "涨价"]},
        }
        tags = detect_tags("Samsung announces price hike", "", config)
        assert len(tags) == 2
        labels = [t[0] for t in tags]
        assert "new" in labels
        assert "price" in labels

    def test_no_false_positive(self):
        config = {
            "supply": {"label": "supply", "class": "tag-supply",
                       "keywords": ["capacity", "fab"]},
        }
        tags = detect_tags("Routine market update", "nothing special here", config)
        assert tags == []

    def test_case_insensitive(self):
        config = {
            "new": {"label": "new", "class": "tag-new",
                    "keywords": ["ANNOUNCE"]},
        }
        tags = detect_tags("company Announces product", "", config)
        assert ("new", "tag-new") in tags

    def test_matches_body_not_title(self):
        config = {
            "tech": {"label": "tech", "class": "tag-tech",
                     "keywords": ["3d nand"]},
        }
        tags = detect_tags("Routine press release", "new 3D NAND technology", config)
        assert ("tech", "tag-tech") in tags


class TestLoadRenderTags:
    """Load render_tags from domain.yaml."""

    def test_loads_from_storage_domain(self):
        domain_path = Path(__file__).parent.parent.parent.parent.parent / \
                      "domains" / "storage" / "domain.yaml"
        if domain_path.exists():
            tags = load_render_tags(str(domain_path))
            assert isinstance(tags, dict)
            assert "new" in tags
            assert "tech" in tags
            assert "supply" in tags
            assert "price" in tags
            assert "keywords" in tags["new"]

    def test_returns_empty_for_none(self):
        assert load_render_tags(None) == {}

    def test_returns_empty_for_missing_file(self):
        assert load_render_tags("/nonexistent/path.yaml") == {}

    def test_returns_empty_for_invalid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: [unclosed")
            f.flush()
            result = load_render_tags(f.name)
        os.unlink(f.name)
        assert result == {}


class TestConvert:
    """Markdown→HTML conversion."""

    def test_convert_basic_item(self):
        md = """# Title

---

### Samsung HBM4 Announcement

- Key point one
- Key point two

*Source: reuters.com · 2026年5月28日*

---"""
        html = convert(md)
        assert '<h3>' in html
        assert 'Samsung' in html
        assert '<div class="item">' in html
        assert '<div class="source">' in html
        assert '<p>' in html
        assert 'Key point one' in html

    def test_convert_summary(self):
        md = """# Title

---

Today's summary paragraph text here.

---

### Item Title

- Body

*Source: reuters.com · 2026年5月28日*"""
        html = convert(md)
        assert '<div class="summary">' in html
        assert "summary paragraph" in html

    def test_convert_section_header(self):
        md = """# Title

### 今日要点

- Key insight

---"""
        html = convert(md)
        assert '<div class="section-title">' in html
        assert '今日要点' in html

    def test_convert_bullet_in_body(self):
        md = """# Title

---

### Item Title

- Point A
- Point B

*Source: reuters.com · 2026年5月28日*"""
        html = convert(md)
        assert 'Point A' in html
        assert 'Point B' in html

    def test_convert_empty(self):
        assert convert("") == ""

    def test_convert_no_items(self):
        md = "# Just a title"
        html = convert(md)
        # Should produce minimal output, no errors
        assert isinstance(html, str)


class TestRealBriefing:
    """Integration test with a real briefing.md (if available)."""

    def test_convert_real_briefing(self):
        """Use the most recent data dir briefing.md if it exists."""
        workspace = Path.home() / "WorkSpace" / "Stratum" / "storage" / "data"
        if workspace.exists():
            # Find most recent date dir
            date_dirs = sorted([d for d in workspace.iterdir() if d.is_dir()], reverse=True)
            for d in date_dirs:
                md_path = d / "briefing.md"
                if md_path.exists():
                    html = convert(md_path.read_text())
                    assert isinstance(html, str)
                    assert len(html) > 100
                    assert "<div" in html  # produces HTML
                    return
        pytest.skip("No recent briefing.md found in workspace")
