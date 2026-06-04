"""Block output policy for Edit stage category writing."""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from .boilerplate import clean_evidence_text
except ImportError:  # pragma: no cover - script/test fallback
    from boilerplate import clean_evidence_text


@dataclass(frozen=True)
class BlockOutputPolicy:
    """Normalize category-block model output and deterministic fallbacks."""

    max_title_chars: int = 140
    max_label_chars: int = 90
    max_paragraphs: int = 2

    def fallback_paragraphs(self, item: dict) -> list[str]:
        evidence = item.get("evidence") or []
        first = evidence[0] if evidence else {}
        title = str(item.get("title_hint") or first.get("title") or "").strip()
        snippet = self._safe_fallback_summary(title)
        if item.get("kind") == "edge":
            return [
                snippet or item.get("title_hint", ""),
                "这个信号值得观察，因为它可能提示产业链边缘变量正在变化；但目前证据仍偏单点，尚不能替代主线供需、价格、产能或客户导入进展判断。",
            ]
        return [
            snippet or item.get("title_hint", ""),
            "这条信息的增量在于它与今日存储产业的供需、技术路线或资本开支判断相关，后续仍需用更多来源验证其持续性。",
        ]

    def _safe_fallback_summary(self, title: str) -> str:
        """Return a neutral summary line without reusing raw scraped article bodies."""
        title = clean_evidence_text(title or "").replace("\n", " ").strip()
        title = re.sub(r"\s+", " ", title)
        title = re.sub(r"^[#>\-\*\s]+", "", title)
        title = title[:80]
        if not title:
            return "该来源提供了当日增量信息。"
        return f"该来源围绕“{title}”提供了当日增量信息。"

    def category_payload(self, category: dict, selected_ids: set[str]) -> dict:
        items = [
            item for item in category.get("items", [])
            if item.get("item_id") in selected_ids
        ]
        return {
            "category_id": category["category_id"],
            "label": category.get("label", ""),
            "why_created": category.get("why_created", ""),
            "items": [
                {
                    "item_id": item["item_id"],
                    "kind": item["kind"],
                    "title_hint": item["title_hint"],
                    "reason": item.get("reason", ""),
                    "evidence": item.get("evidence", []),
                }
                for item in items
            ],
            "dropped": category.get("dropped", []),
        }

    def fallback_block(self, category: dict, items: list[dict], detail: str) -> dict:
        return {
            "category_id": category["category_id"],
            "label": category.get("label", ""),
            "status": "fallback",
            "detail": detail,
            "items": [
                {
                    "item_id": item["item_id"],
                    "title": item["title_hint"],
                    "paragraphs": self.fallback_paragraphs(item),
                    "_fallback": detail,
                }
                for item in items
            ],
            "dropped": category.get("dropped", []),
        }

    def normalize_response(self, parsed: dict | None, category: dict, items: list[dict]) -> dict:
        if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
            return self.fallback_block(category, items, "invalid_json")

        by_id = {item["item_id"]: item for item in items}
        normalized = []
        for generated in parsed.get("items", []):
            entry = self._normalize_generated_item(generated, by_id)
            if entry:
                normalized.append(entry)

        generated_ids = {entry["item_id"] for entry in normalized}
        missing = [item for item in items if item["item_id"] not in generated_ids]
        normalized.extend(self.fallback_block(category, missing, "missing_from_llm")["items"])
        dropped = parsed.get("dropped") if isinstance(parsed.get("dropped"), list) else category.get("dropped", [])
        return {
            "category_id": category["category_id"],
            "label": str(parsed.get("label") or category.get("label", "")).strip()[:self.max_label_chars],
            "status": "ok",
            "detail": "",
            "items": normalized,
            "dropped": dropped,
        }

    def _normalize_generated_item(self, generated: object, planned_items: dict[str, dict]) -> dict | None:
        if not isinstance(generated, dict):
            return None
        item_id = str(generated.get("item_id") or "").strip()
        planned = planned_items.get(item_id)
        if not planned:
            return None
        paragraphs = generated.get("paragraphs")
        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]
        if not isinstance(paragraphs, list) or not paragraphs:
            paragraphs = self.fallback_paragraphs(planned)
        clean_paragraphs = [
            cleaned
            for paragraph in paragraphs
            for cleaned in [clean_evidence_text(paragraph)]
            if cleaned
        ][:self.max_paragraphs]
        return {
            "item_id": item_id,
            "title": str(generated.get("title") or planned["title_hint"]).strip()[:self.max_title_chars],
            "paragraphs": clean_paragraphs or self.fallback_paragraphs(planned),
        }
