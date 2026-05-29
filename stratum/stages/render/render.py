#!/usr/bin/env python3
"""render.py — MD→HTML→PDF for Stratum briefing (daily/weekly/monthly/quarterly/yearly).

Domain-agnostic. Template-driven: reads an HTML template file, fills {{TITLE}}/{{BODY}}/etc.
Tag detection keywords loaded from domain.yaml editorial.render_tags.

Architecture:
    render.py is briefing-type-agnostic. It does NOT know about daily vs weekly.
    The CALLER (pipeline.py, SKILL.md, cron) selects the template file via --template.
    To add a new briefing type: create a template .html file — no code changes needed.

Template placeholders: {title} {date_str} {weekday} {body} {footer}
CSS braces in templates must be escaped as {{{{ and }}}}.

Input:  briefing.md + template.html + domain.yaml (for render_tags)
Output: briefing.html + briefing.pdf in --output-dir
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
import argparse, re, os, subprocess, sys, yaml
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


def detect_tags(title, body, tag_config):
    """Match title+body against domain-configured keyword sets. Returns [(label, css_class), ...]."""
    tags = []
    if not tag_config:
        return tags
    t = (title + " " + body).lower()
    for tag_id, cfg in tag_config.items():
        keywords = cfg.get("keywords", [])
        if any(w.lower() in t for w in keywords):
            tags.append((cfg.get("label", tag_id), cfg.get("class", f"tag-{tag_id}")))
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


def convert(md_text):
    """Convert Stratum briefing markdown to HTML body. Domain-agnostic."""
    lines = md_text.split("\n")
    body_parts = []
    item_lines = []
    in_item = False
    in_section = False
    item_num = 0
    first_hr_seen = False
    summary_collected = False

    for raw in lines:
        s = raw.strip()
        if not s:
            if in_item:
                item_lines.append("<br>")
            continue

        if s.startswith("---"):
            if in_item:
                body_parts.append("\n".join(item_lines))
                body_parts.append("</div>\n")
                item_lines = []
                in_item = False
                in_section = False
            body_parts.append("<hr>\n")
            first_hr_seen = True
            summary_collected = False
            continue

        if s.startswith("# ") or s.startswith("## "):
            continue

        if s.startswith("### "):
            if in_item:
                body_parts.append("\n".join(item_lines))
                body_parts.append("</div>\n")
                item_lines = []
                in_item = False

            title = s[4:].strip()
            title_esc = esc(title)

            if any(kw in title for kw in ["关注", "反向信号", "今日要点"]):
                in_section = True
                body_parts.append(f'<div class="section-title">{title_esc}</div>\n')
                continue

            item_num += 1
            in_item = True
            in_section = False
            item_lines = [
                '<div class="item">',
                f'<h3><span class="num">{item_num}</span>{title_esc}</h3>',
            ]
            continue

        if s.startswith("*") and s.endswith("*") and "·" in s:
            text = s.strip("* ").strip()
            if in_item:
                item_lines.append(f'<div class="source">{esc(text)}</div>')
                body_parts.append("\n".join(item_lines))
                body_parts.append("</div>\n")
                item_lines = []
                in_item = False
            continue

        if s.startswith("- "):
            text = esc(s[2:].strip())
            if in_section:
                body_parts.append(f'<div class="bullet">· {text}</div>\n')
            elif in_item:
                item_lines.append(f"<p>{text}</p>")
            else:
                body_parts.append(f'<div class="bullet">· {text}</div>\n')
            continue

        if first_hr_seen and not summary_collected and not in_item and not s.startswith("#"):
            body_parts.append(f'<div class="summary"><p>{esc(s)}</p></div>\n')
            summary_collected = True
            continue

        if in_item:
            item_lines.append(f"<p>{esc(s)}</p>")
        else:
            body_parts.append(f"<p>{esc(s)}</p>")

    if in_item:
        body_parts.append("\n".join(item_lines))
        body_parts.append("</div>\n")

    return "".join(body_parts)


def render_html(md_path, output_dir, title, date_str, weekday, footer, template_str):
    """Render briefing.md → HTML using the provided template string."""
    with open(md_path) as f:
        md = f.read()

    body_html = convert(md)

    html = template_str.format(
        title=title,
        date_str=date_str,
        weekday=weekday,
        body=body_html,
        footer=footer,
    )

    html_path = os.path.join(output_dir, "briefing.html")
    with open(html_path, "w") as f:
        f.write(html)
    return html_path


def render_pdf(html_path, output_dir):
    pdf_path = os.path.join(output_dir, "briefing.pdf")
    result = subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", "--no-margins", f"file://{html_path}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"PDF render failed: {result.stderr[-300:]}", file=sys.stderr)
        return None
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
    parser.add_argument("--footer", default="由 AI Agent 自动生成",
                        help="Footer text (e.g. '由 AI Agent 自动生成 · 每日 7:30 CST')")
    args = parser.parse_args()

    # Auto-derive date/weekday if not provided
    date_str = args.date
    weekday = args.weekday
    if not date_str or not weekday:
        now = datetime.now(CST)
        if not date_str:
            date_str = f"{now.year}年{now.month}月{now.day}日"
        if not weekday:
            weekday = WEEKDAY_ZH[now.weekday()]

    os.makedirs(args.output_dir, exist_ok=True)

    # Load template (with fallback)
    template_str = load_template(args.template)

    print(f"📄 Rendering: {args.input}", file=sys.stderr)
    html_path = render_html(args.input, args.output_dir, args.title, date_str, weekday,
                            args.footer, template_str)
    print(f"   HTML: {html_path}", file=sys.stderr)

    pdf_path = render_pdf(html_path, args.output_dir)
    if pdf_path:
        print(f"   PDF:  {pdf_path}", file=sys.stderr)
    print(f"✅ Render complete", file=sys.stderr)

    print(os.path.abspath(args.output_dir))


if __name__ == "__main__":
    main()
