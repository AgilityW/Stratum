#!/usr/bin/env python3
"""render.py — MD→HTML→PDF for Stratum briefing (daily/weekly/monthly/quarterly/yearly).

Domain-agnostic. Template-driven: reads an HTML template file, fills {{TITLE}}/{{BODY}}/etc.
Tag detection keywords loaded from domain.yaml editorial.render_tags.

Architecture:
    render.py is briefing-type-agnostic. It does NOT know about daily vs weekly.
    The CALLER (pipeline.py, SKILL.md, cron) selects the template file via --template.
    To add a new briefing type: create a template .html file — no code changes needed.

Template placeholders: {title} {date_str} {weekday} {body} {footer} {artifact_name}
CSS braces in templates must be escaped as {{{{ and }}}}.

Input:  briefing.md + template.html + domain.yaml (for render_tags)
Output: <artifact-name>.html + <artifact-name>.pdf in --output-dir
Side effects: Writes files. Invokes Chrome headless subprocess (system call).
Invariants:  HTML output is self-contained (all CSS inline). PDF via Chrome --headless.
Error behavior: Chrome not found → PDF skipped, HTML still generated.
                Template not found → falls back to built-in default template.
                Missing --domain → tags disabled (empty dict).

Usage:
    python3 render.py --input briefing.md --output-dir /path/to/output \
        --title "存储早报" --date "2026年5月30日" --weekday "周五" \
        --template domains/storage/templates/daily.html \
        --domain domains/storage/domain.yaml \
        --footer "由 AI Agent 自动生成 · 每日 7:30 CST"
"""
from __future__ import annotations
import argparse, re, os, shutil, subprocess, sys, yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# Built-in default template — used when no --template provided or file not found
_BUILTIN_TEMPLATE = str(Path(__file__).parent / "templates" / "default.html")


def esc(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


def load_render_tags(domain_path: str | None) -> dict:
    """Load render_tags from domain.yaml editorial section. Returns empty dict if not found."""
    if not domain_path:
        return {}
    try:
        with open(domain_path) as f:
            config = yaml.safe_load(f)
        editorial = config.get("editorial", {})
        return editorial.get("render_tags", {})
    except Exception:
        return {}


def detect_tags(title, body, tag_config, require_tag: bool = False):
    """Match title+body against domain-configured keyword sets.

    When require_tag is true, return a default `new` badge if no configured
    keyword matches so every rendered item has a visible category marker.
    """
    tags = []
    if not tag_config:
        return [("new", "tag-new")] if require_tag else tags
    t = (title + " " + body).lower()
    for tag_id, cfg in tag_config.items():
        keywords = cfg.get("keywords", [])
        if any(w.lower() in t for w in keywords):
            tags.append((cfg.get("label", tag_id), cfg.get("class", f"tag-{tag_id}")))
    if require_tag and not tags:
        fallback = tag_config.get("new") or next(iter(tag_config.values()), {})
        tags.append((fallback.get("label", "new"), fallback.get("class", "tag-new")))
    return tags


def load_template(template_path: str | None) -> str:
    """Load HTML template from file. Falls back to built-in default if not found.

    Template must use Python str.format() syntax with these keys:
        {title} {date_str} {weekday} {body} {footer}
    CSS braces must be doubled: {{ and }}.
    """
    # Try user-provided path
    if template_path and os.path.exists(template_path):
        with open(template_path) as f:
            return f.read()

    # Fall back to built-in
    if os.path.exists(_BUILTIN_TEMPLATE):
        print(f"⚠️  Template not found: {template_path}. Using built-in default.",
              file=sys.stderr)
        with open(_BUILTIN_TEMPLATE) as f:
            return f.read()

    # Ultimate fallback — minimal valid HTML
    print("⚠️  No template available. Using hardcoded minimal HTML.", file=sys.stderr)
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{title}</title></head>
<body><h1>{title}</h1><p>{date_str} · {weekday}</p><div>{body}</div><footer>{footer}</footer></body></html>"""


def _slug_part(text: str) -> str:
    """Return a filesystem-safe title-case filename segment."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:1].upper() + text[1:] if text else "Briefing"


def artifact_basename(domain: str, briefing_type: str, run_date: str) -> str:
    """Build stable artifact names like Storage_Daily_Briefing_2026-05-30."""
    return f"{_slug_part(domain)}_{_slug_part(briefing_type)}_Briefing_{run_date}"


def _legacy_copy(path: str, legacy_name: str) -> None:
    legacy_path = os.path.join(os.path.dirname(path), legacy_name)
    if os.path.abspath(path) != os.path.abspath(legacy_path):
        shutil.copyfile(path, legacy_path)


def _render_tag_spans(tags):
    """Render item tag badges."""
    return "".join(
        f'<span class="tag {esc(css_class)}">{esc(label)}</span>'
        for label, css_class in tags
    )


def _clean_source_line_display(text: str) -> str:
    """Remove machine locale tags from rendered source lines."""
    return re.sub(r"\s*\[(?:[A-Za-z]{2,3}(?:-[A-Za-z]{2,8}){0,2})\]", "", text).strip()


MAJOR_SECTION_TITLES = {"今日要点", "行业要点", "产业信号", "特别关注", "反向信号"}
NON_ITEM_SECTION_TITLES = MAJOR_SECTION_TITLES | {"关注"}


def convert(md_text, tag_config=None):
    """Convert Stratum briefing markdown to HTML body. Domain-agnostic."""
    tag_config = tag_config or {}
    lines = md_text.split("\n")
    body_parts = []
    item_lines = []
    item_title = ""
    item_tag_text = []
    in_item = False
    in_section = False
    section_kind = ""
    item_num = 0
    first_hr_seen = False
    summary_collected = False

    def flush_item():
        nonlocal item_lines, item_title, item_tag_text, in_item
        if not in_item:
            return
        is_edge_signal = item_title.startswith("【边缘信号】")
        display_title = item_title.replace("【边缘信号】", "", 1).strip() if is_edge_signal else item_title
        title_esc = esc(display_title)
        tags = detect_tags(
            item_title,
            " ".join(item_tag_text),
            tag_config,
            require_tag=True,
        )
        if is_edge_signal:
            tags = [("edge", "tag-edge")] + [(label, css) for label, css in tags if css != "tag-edge"]
        tags_html = _render_tag_spans(tags)
        item_class = "item edge-signal" if is_edge_signal else "item"
        body_parts.append(
            f'<div class="{item_class}">\n'
            f'<h3><span class="num">{item_num}</span>{title_esc}{tags_html}</h3>'
        )
        body_parts.append("\n".join(item_lines))
        body_parts.append("</div>\n")
        item_lines = []
        item_title = ""
        item_tag_text = []
        in_item = False

    for raw in lines:
        s = raw.strip()
        if not s:
            if in_item:
                item_lines.append("<br>")
            continue

        if s.startswith("---"):
            flush_item()
            in_section = False
            body_parts.append("<hr>\n")
            first_hr_seen = True
            summary_collected = False
            continue

        if s.startswith("# "):
            continue

        if s.startswith("## "):
            flush_item()
            title = s[3:].strip()
            title_esc = esc(title)
            if "年" in title and "月" in title and "日" in title:
                continue
            if title in MAJOR_SECTION_TITLES:
                in_section = True
                section_kind = title if title == "今日要点" else ""
                body_parts.append(f'<div class="major-section">{title_esc}</div>\n')
            else:
                in_section = False
                section_kind = ""
                body_parts.append(f'<div class="subsection-title">{title_esc}</div>\n')
            continue

        if s.startswith("### "):
            flush_item()

            title = s[4:].strip()
            title_esc = esc(title)

            if title in NON_ITEM_SECTION_TITLES:
                in_section = True
                section_kind = title if title == "今日要点" else ""
                body_parts.append(f'<div class="section-title">{title_esc}</div>\n')
                continue

            item_num += 1
            in_item = True
            in_section = False
            item_title = title
            item_tag_text = []
            item_lines = []
            continue

        if s.startswith("*") and s.endswith("*") and "·" in s:
            text = s.strip("* ").strip()
            if in_item:
                item_lines.append(f'<div class="source">{esc(_clean_source_line_display(text))}</div>')
                flush_item()
            continue

        if s.startswith("- "):
            text = esc(s[2:].strip())
            if in_section:
                body_parts.append(f'<div class="bullet">· {text}</div>\n')
            elif in_item:
                item_lines.append(f"<p>{text}</p>")
                item_tag_text.append(s[2:].strip())
            else:
                body_parts.append(f'<div class="bullet">· {text}</div>\n')
            continue

        if section_kind and not in_item and not s.startswith("#"):
            body_parts.append(f'<div class="summary"><p>{esc(s)}</p></div>\n')
            section_kind = ""
            continue

        if first_hr_seen and not summary_collected and not in_item and not s.startswith("#"):
            body_parts.append(f'<div class="summary"><p>{esc(s)}</p></div>\n')
            summary_collected = True
            continue

        if in_item:
            item_lines.append(f"<p>{esc(s)}</p>")
            item_tag_text.append(s)
        else:
            body_parts.append(f"<p>{esc(s)}</p>")

    flush_item()

    return "".join(body_parts)


def render_html(md_path, output_dir, title, date_str, weekday, footer, template_str,
                artifact_name="briefing", write_legacy=False, tag_config=None):
    """Render briefing.md → HTML using the provided template string."""
    with open(md_path) as f:
        md = f.read()

    body_html = convert(md, tag_config=tag_config)

    html = template_str.format(
        title=title,
        date_str=date_str,
        weekday=weekday,
        body=body_html,
        footer=footer,
        artifact_name=artifact_name,
    )

    html_path = os.path.join(output_dir, f"{artifact_name}.html")
    with open(html_path, "w") as f:
        f.write(html)
    if write_legacy:
        _legacy_copy(html_path, "briefing.html")
    return html_path


def render_pdf(html_path, output_dir, artifact_name="briefing", write_legacy=False):
    pdf_path = os.path.join(output_dir, f"{artifact_name}.pdf")
    if not os.path.exists(CHROME):
        print(f"PDF render skipped: Chrome not found at {CHROME}", file=sys.stderr)
        return None
    try:
        result = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf_path}", "--no-margins", f"file://{html_path}"],
            capture_output=True, text=True, timeout=30,
        )
    except OSError as e:
        print(f"PDF render skipped: {e}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"PDF render failed: {result.stderr[-300:]}", file=sys.stderr)
        return None
    if write_legacy:
        _legacy_copy(pdf_path, "briefing.pdf")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="MD→HTML→PDF render for Stratum briefing")
    parser.add_argument("--input", "-i", required=True, help="Input briefing.md")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory")
    parser.add_argument("--title", default="Briefing", help="Page title")
    parser.add_argument("--date", help="Date string (e.g. '2026年5月30日')")
    parser.add_argument("--weekday", help="Weekday (e.g. '周五')")
    parser.add_argument("--template", help="Path to HTML template file (default: built-in)")
    parser.add_argument("--domain", help="Path to domain.yaml (for render_tags)")
    parser.add_argument("--domain-id", default="storage",
                        help="Domain name for artifact filename (e.g. storage)")
    parser.add_argument("--briefing-type", default="daily",
                        help="Briefing type for artifact filename (e.g. daily)")
    parser.add_argument("--artifact-name",
                        help="Output basename without extension. Defaults to Domain_Type_Briefing_YYYY-MM-DD")
    parser.add_argument("--legacy-names", action="store_true",
                        help="Also write briefing.html/pdf compatibility copies")
    parser.add_argument("--footer", default="由 AI Agent 自动生成",
                        help="Footer text (e.g. '由 AI Agent 自动生成 · 每日 7:30 CST')")
    args = parser.parse_args()

    # Auto-derive display date/weekday if not provided. ISO dates are accepted
    # for artifact naming and rendered as Chinese dates in the template.
    run_dt = datetime.now(CST)
    date_str = args.date
    if args.date:
        iso_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", args.date)
        cn_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", args.date)
        if iso_match:
            run_dt = datetime.fromisoformat(iso_match.group(0)).replace(tzinfo=CST)
            date_str = f"{run_dt.year}年{run_dt.month}月{run_dt.day}日"
        elif cn_match:
            y, m, d = map(int, cn_match.groups())
            run_dt = datetime(y, m, d, tzinfo=CST)
    if not date_str:
        date_str = f"{run_dt.year}年{run_dt.month}月{run_dt.day}日"
    weekday = args.weekday or WEEKDAY_ZH[run_dt.weekday()]

    os.makedirs(args.output_dir, exist_ok=True)

    # Load template (with fallback)
    template_str = load_template(args.template)
    run_date = run_dt.date().isoformat()
    artifact_name = args.artifact_name or artifact_basename(
        args.domain_id, args.briefing_type, run_date
    )

    print(f"📄 Rendering: {args.input}", file=sys.stderr)
    tag_config = load_render_tags(args.domain)
    html_path = render_html(args.input, args.output_dir, args.title, date_str, weekday,
                            args.footer, template_str, artifact_name,
                            write_legacy=args.legacy_names,
                            tag_config=tag_config)
    print(f"   HTML: {html_path}", file=sys.stderr)

    pdf_path = render_pdf(html_path, args.output_dir, artifact_name,
                          write_legacy=args.legacy_names)
    if pdf_path:
        print(f"   PDF:  {pdf_path}", file=sys.stderr)
    print(f"✅ Render complete", file=sys.stderr)

    print(os.path.abspath(args.output_dir))


if __name__ == "__main__":
    main()
