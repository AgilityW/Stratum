"""Tests for render stage."""
import json
import os
import tempfile
import pytest
from pathlib import Path

# Import render functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from render import (
    esc, detect_tags, load_render_tags, load_template, render_html, convert,
    render_pdf, artifact_basename,
)


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

    def test_convert_applies_configured_tags(self):
        md = """# Title

---

### Samsung announces HBM4

- Point one

*Source: test.com · 2026年5月29日*"""
        html = convert(md, {
            "new": {
                "label": "new",
                "class": "tag-new",
                "keywords": ["announce"],
            }
        })
        assert '<span class="tag tag-new">new</span>' in html

    def test_convert_applies_tags_from_item_body(self):
        md = """# Title

---

### Routine market note

Samsung and Micron supply constraints pushed contract price expectations higher.

*Source: test.com · 2026年5月29日*"""
        html = convert(md, {
            "price": {
                "label": "price",
                "class": "tag-price",
                "keywords": ["contract price"],
            }
        })
        assert '<span class="tag tag-price">price</span>' in html

    def test_convert_strips_source_locale_tags(self):
        md = """# Title

---

### Item Title

Detail text.

*Digitimes [en], cnstock.com [zh-CN] · 2026年5月30日*"""
        html = convert(md)
        assert "Digitimes, cnstock.com · 2026年5月30日" in html
        assert "[en]" not in html
        assert "[zh-CN]" not in html

    def test_convert_strips_case_variant_source_locale_tags(self):
        md = """# Title

---

### Item Title

Detail text.

*Digitimes [EN], cnstock.com [zh-cn], example.jp [zh-Hans-CN] · 2026年5月30日*"""
        html = convert(md)
        assert "Digitimes, cnstock.com, example.jp · 2026年5月30日" in html
        assert "[EN]" not in html
        assert "[zh-cn]" not in html
        assert "[zh-Hans-CN]" not in html

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


class TestLoadTemplate:
    """Template file loading with fallback."""

    def test_loads_storage_daily_template(self):
        template_path = Path(__file__).parent.parent.parent.parent.parent / \
                        "domains" / "storage" / "templates" / "daily.html"
        if template_path.exists():
            tmpl = load_template(str(template_path))
            assert "{title}" in tmpl
            assert "{body}" in tmpl
            assert "{footer}" in tmpl
            assert "daily" not in tmpl.lower() or "<!DOCTYPE html>" in tmpl

    def test_loads_robot_daily_template(self):
        template_path = Path(__file__).parent.parent.parent.parent.parent / \
                        "domains" / "robot" / "templates" / "daily.html"
        if template_path.exists():
            tmpl = load_template(str(template_path))
            assert "{title}" in tmpl
            assert "{body}" in tmpl

    def test_falls_back_for_missing_file(self):
        tmpl = load_template("/nonexistent/template.html")
        assert "{title}" in tmpl  # built-in default should have placeholders
        assert "{body}" in tmpl

    def test_falls_back_for_none(self):
        tmpl = load_template(None)
        assert "{title}" in tmpl
        assert "{body}" in tmpl

    def test_fallback_produces_valid_html(self):
        tmpl = load_template(None)
        # Should be valid HTML with key placeholders
        assert "<!DOCTYPE html>" in tmpl or "<html" in tmpl
        assert "{title}" in tmpl
        assert "{body}" in tmpl
        assert "{footer}" in tmpl


class TestArtifactName:
    """Stable report artifact naming."""

    def test_artifact_basename(self):
        assert artifact_basename("storage", "daily", "2026-05-30") == \
            "Storage_Daily_Briefing_2026-05-30"


class TestRenderHtml:
    """render_html() with template string."""

    def test_renders_with_default_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = os.path.join(tmpdir, "test.md")
            with open(md_path, "w") as f:
                f.write("""# Test

---

### Test Item

- Point one

*Source: test.com · 2026年5月29日*""")

            tmpl = load_template(None)
            html_path = render_html(md_path, tmpdir, "Test Briefing",
                                    "2026年5月29日", "周四",
                                    "Test footer", tmpl,
                                    artifact_name="Storage_Daily_Briefing_2026-05-29",
                                    write_legacy=True,
                                    tag_config={
                                        "new": {
                                            "label": "new",
                                            "class": "tag-new",
                                            "keywords": ["Test Item"],
                                        }
                                    })
            assert os.path.exists(html_path)
            assert html_path.endswith("Storage_Daily_Briefing_2026-05-29.html")
            assert os.path.exists(os.path.join(tmpdir, "briefing.html"))
            with open(html_path) as f:
                content = f.read()
            assert "<!DOCTYPE html>" in content
            assert "Test Briefing" in content
            assert "Test footer" in content
            assert "Point one" in content
            assert 'class="tag tag-new"' in content

    def test_renders_with_domain_template(self):
        template_path = Path(__file__).parent.parent.parent.parent.parent / \
                        "domains" / "storage" / "templates" / "daily.html"
        if not template_path.exists():
            pytest.skip("storage daily template not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = os.path.join(tmpdir, "test.md")
            with open(md_path, "w") as f:
                f.write("""# Title

---

### An Item

- Detail

*Source: reuters.com · 2026年5月29日*""")

            tmpl = load_template(str(template_path))
            html_path = render_html(md_path, tmpdir, "早报",
                                    "2026年5月29日", "周四",
                                    "Auto-generated", tmpl,
                                    artifact_name="Storage_Daily_Briefing_2026-05-29")
            assert os.path.exists(html_path)
            with open(html_path) as f:
                content = f.read()
            assert "<!DOCTYPE html>" in content
            assert "早报" in content
            assert "An Item" in content
            assert "Storage_Daily_Briefing_2026-05-29" not in content


class TestRenderPdf:
    """PDF rendering shell-out behavior."""

    def test_skips_when_chrome_missing(self, monkeypatch):
        import render

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, "briefing.html")
            Path(html_path).write_text("<html><body>ok</body></html>")

            monkeypatch.setattr(render, "CHROME", "/definitely/missing/chrome")
            assert render_pdf(html_path, tmpdir, "Storage_Daily_Briefing_2026-05-29") is None
