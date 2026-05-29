#!/usr/bin/env python3
"""render.py — MD→HTML→PDF for Stratum daily briefing.

Domain-agnostic. Uses Chrome headless for PDF.
Template expects: {{TITLE}}, {{DATE}}, {{WEEKDAY}}, {{CONTENT}}, {{FOOTER}}.

Usage:
    python3 render.py --input briefing.md --output-dir /path/to/output \
        --title "存储早报" --date "2026年5月30日" --weekday "周五"
"""
import argparse, re, os, subprocess, sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def esc(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


def detect_tags(title, body):
    tags = []
    t = (title + " " + body).lower()
    if any(w in t for w in ["announce", "launch", "release", "unveil", "debut", "推出", "发布", "発表"]):
        tags.append(("new", "tag-new"))
    if any(w in t for w in ["nm", "layer", "process", "architecture", "制程", "工艺", "堆叠"]):
        tags.append(("tech", "tag-tech"))
    if any(w in t for w in ["capacity", "expansion", "fab", "plant", "扩产", "产能", "晶圆厂"]):
        tags.append(("supply", "tag-supply"))
    if any(w in t for w in ["price", "hike", "shortage", "涨价", "价格"]):
        tags.append(("price", "tag-price"))
    return tags


def convert(md_text):
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


def render_html(md_path, output_dir, title, date_str, weekday):
    with open(md_path) as f:
        md = f.read()

    body_html = convert(md)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#fafbfc;color:#1a1a1a;max-width:640px;margin:0 auto;padding:0}}
  .header{{background:#0f172a;color:#fff;padding:32px 28px 24px}}
  .header h1{{font-size:20px;font-weight:700;margin-bottom:6px}}
  .header .date{{font-size:13px;color:#94a3b8}}
  .content{{padding:28px 28px 40px;background:#fff}}
  .summary{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:18px 20px;margin-bottom:28px}}
  .summary p{{font-size:15px;line-height:1.85;color:#1e3a5f;margin:0}}
  hr{{border:none;border-top:1px solid #e2e8f0;margin:28px 0}}
  .item{{margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid #f1f5f9}}
  .item:last-of-type{{border-bottom:none}}
  .item .num{{display:inline-block;width:26px;height:26px;line-height:26px;text-align:center;background:#1e3a5f;color:#fff;font-size:12px;font-weight:700;border-radius:4px;margin-right:10px;vertical-align:middle}}
  .item .tag{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:.5px;margin-left:8px;vertical-align:middle}}
  .tag-new{{background:#dcfce7;color:#166534}}
  .tag-tech{{background:#fef3c7;color:#92400e}}
  .tag-supply{{background:#f3e8ff;color:#6b21a8}}
  .tag-price{{background:#fce7f3;color:#9d174d}}
  .item h3{{font-size:16px;font-weight:700;color:#0f172a;margin-bottom:10px;line-height:1.5}}
  .item p{{font-size:14.5px;line-height:1.8;color:#334155;margin-bottom:8px}}
  .item .source{{font-size:11px;color:#94a3b8}}
  .section-title{{font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:1.2px;margin:32px 0 16px}}
  .bullet{{font-size:14px;line-height:1.7;color:#475569;margin:8px 0;padding-left:16px;position:relative}}
  .bullet::before{{content:"▸";position:absolute;left:0;color:#3b82f6;font-size:10px;line-height:1.7}}
  .footer{{text-align:center;padding:20px 28px 36px;background:#fafbfc;font-size:10px;color:#cbd5e1;border-top:1px solid #f1f5f9}}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="date">{date_str} · {weekday}</div>
</div>
<div class="content">
{body_html}
</div>
<div class="footer">由 AI Agent 自动生成 · 每日 7:30 CST</div>
</body>
</html>"""

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

    print(f"📄 Rendering: {args.input}", file=sys.stderr)
    html_path = render_html(args.input, args.output_dir, args.title, date_str, weekday)
    print(f"   HTML: {html_path}", file=sys.stderr)

    pdf_path = render_pdf(html_path, args.output_dir)
    if pdf_path:
        print(f"   PDF:  {pdf_path}", file=sys.stderr)
    print(f"✅ Render complete", file=sys.stderr)

    print(os.path.abspath(args.output_dir))


if __name__ == "__main__":
    main()
