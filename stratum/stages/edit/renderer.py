"""Deterministic Markdown rendering for Edit stage reports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

try:
    from .block_policy import BlockOutputPolicy
    from .boilerplate import clean_evidence_text
    from .source_repair import (
        _article_date_label,
        _article_source_label,
        _best_article_for_item,
    )
except ImportError:  # pragma: no cover - script/test fallback
    from block_policy import BlockOutputPolicy
    from boilerplate import clean_evidence_text
    from source_repair import (
        _article_date_label,
        _article_source_label,
        _best_article_for_item,
    )


CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass
class EditRenderer:
    """Render planned and generated edit blocks into final Markdown."""

    template_dir: str
    block_policy: BlockOutputPolicy

    def format_cn_date(self, date_str: str) -> str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekday = CST_WEEKDAYS[dt.weekday()]
            return f"{dt.year}年{dt.month}月{dt.day}日 · {weekday}"
        except ValueError:
            return date_str

    def assemble_block_markdown(self, plan: dict, blocks: list[dict], run_date: str) -> tuple[str, str]:
        generated = self._block_item_map(blocks)
        block_by_category = {block.get("category_id"): block for block in blocks}
        item_by_id = {item["item_id"]: item for item in plan.get("items", [])}
        main_parts = []
        edge_parts = []

        for category in plan.get("categories", []):
            selected = [
                item_by_id[item["item_id"]]
                for item in category.get("items", [])
                if item.get("item_id") in item_by_id and item_by_id[item["item_id"]].get("kind") == "main"
            ]
            if not selected:
                continue
            label = (block_by_category.get(category["category_id"], {}) or {}).get("label") or category.get("label", "")
            main_parts.append(f"## {label}\n\n")
            for item in selected:
                written = generated.get(item["item_id"], {})
                title = str(written.get("title") or item["title_hint"]).strip()
                paragraphs = written.get("paragraphs") or self.block_policy.fallback_paragraphs(item)
                main_parts.append(f"### {title}\n")
                for paragraph in paragraphs[:self.block_policy.max_paragraphs]:
                    paragraph = clean_evidence_text(paragraph)
                    if paragraph:
                        main_parts.append(f"\n{paragraph}\n")
                main_parts.append(f"\n{self.source_line(item, run_date, title, paragraphs)}\n\n")

        for item in plan.get("items", []):
            if item.get("kind") != "edge":
                continue
            written = generated.get(item["item_id"], {})
            title = str(written.get("title") or item["title_hint"]).strip()
            if not title.startswith("【边缘信号】"):
                title = f"【边缘信号】{title}"
            paragraphs = written.get("paragraphs") or self.block_policy.fallback_paragraphs(item)
            edge_parts.append(f"### {title}\n")
            for paragraph in paragraphs[:self.block_policy.max_paragraphs]:
                paragraph = clean_evidence_text(paragraph)
                if paragraph:
                    edge_parts.append(f"\n{paragraph}\n")
            edge_parts.append(f"\n{self.source_line(item, run_date, title, paragraphs)}\n\n")

        return "".join(main_parts).strip(), "".join(edge_parts).strip()

    def assemble_profile_markdown(
        self,
        title: str,
        run_date: str,
        template_name: str,
        sections: dict,
        main_markdown: str,
        edge_markdown: str,
    ) -> str:
        briefing = self.render_template(template_name, {
            "title": title,
            "date_label": self.format_cn_date(run_date),
            "summary": self._paragraph_block(sections["summary"]),
            "main_categories": main_markdown,
            "edge_items": edge_markdown,
            "focus": self._bullet_block(sections["focus"]),
            "contrarian": self._bullet_block(sections["contrarian"]),
        })
        return briefing.strip() + "\n"

    def render_template(self, template_name: str, values: dict) -> str:
        template_path = os.path.join(self.template_dir, template_name)
        if not os.path.exists(template_path):
            template_path = os.path.join(self.template_dir, "daily.md")
        with open(template_path) as f:
            text = f.read()
        for key, value in values.items():
            text = text.replace("{{ " + key + " }}", str(value))
        return text

    def source_line(self, item: dict, run_date: str, title: str = "", paragraphs: list[str] | None = None) -> str:
        supporting_article = _best_article_for_item(
            title,
            paragraphs or [],
            item.get("evidence", []),
        )
        if supporting_article:
            source = _article_source_label(supporting_article)
            return f"*{source} · {_article_date_label(supporting_article, run_date)}*"

        sources = [source for source in item.get("sources", []) if source]
        dates = item.get("dates", []) or [run_date]
        date = max(str(d) for d in dates if d)
        return f"*{', '.join(sources)} · {self._date_cn(date, run_date)}*"

    def _date_cn(self, date_text: str, fallback: str) -> str:
        try:
            dt = datetime.fromisoformat((date_text or fallback)[:10])
            return f"{dt.year}年{dt.month}月{dt.day}日"
        except ValueError:
            return self.format_cn_date(fallback).split(" · ")[0]

    def _block_item_map(self, blocks: list[dict]) -> dict[str, dict]:
        mapped = {}
        for block in blocks:
            for item in block.get("items", []):
                mapped[item.get("item_id")] = item
        return mapped

    def _paragraph_block(self, items: list[str]) -> str:
        return "\n".join(str(item).strip() for item in items if str(item).strip())

    def _bullet_block(self, items: list[str]) -> str:
        return "\n".join(f"- {str(item).strip()}" for item in items if str(item).strip())
