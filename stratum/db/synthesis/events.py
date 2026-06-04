"""Synthesized event construction for DB-native synthesis."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any

CST = timezone(timedelta(hours=8))


class SynthesizedEventBuilder:
    """Build target-scale event rows from ranked lower-scale thread groups."""

    def build(
        self,
        *,
        report_id: str,
        target_scale: str,
        target_period: str,
        event_date: str,
        thread_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        events = []
        for index, group in enumerate(thread_groups, start=1):
            source_events = group["events"]
            events.append({
                "id": f"ev-{self.slug(target_period)}-{group['thread_id']}",
                "thread_id": group["thread_id"],
                "scale": target_scale,
                "date": event_date,
                "title": self.synthesis_title(target_scale, source_events),
                "article_ids": self.unique_flatten(source_events, "article_ids")[:20],
                "entity_ids": self.unique_flatten(source_events, "entity_ids")[:12],
                "term_ids": self.unique_flatten(source_events, "term_ids")[:12],
                "source_domains": self.unique_flatten(source_events, "source_domains")[:12],
                "confidence": self.lowest_confidence(source_events),
                "briefing_id": f"{target_scale}-{target_period}",
                "created_at": datetime.now(CST).isoformat(),
                "status": "active",
                "priority": min(index, 3),
                "source_event_ids": [event["id"] for event in source_events if event.get("id")],
                "report_id": report_id,
            })
        return events

    def synthesis_title(self, target_scale: str, events: list[dict[str, Any]]) -> str:
        theme = self.thread_theme((events[0].get("thread_id") if events else "") or "", events)
        lead = self.lead_event_for_theme(theme, events)
        lead_title = lead.get("title") or lead.get("thread_id") or theme
        return theme if theme == lead_title else f"{theme}：{lead_title}"

    def thread_theme(self, thread_id: str, events: list[dict[str, Any]]) -> str:
        text = " ".join([thread_id] + [event.get("title", "") for event in events]).lower()
        if "cxmt" in text or "ymtc" in text or "长鑫" in text or "长存" in text or "中国存储" in text:
            return "中国存储扩张"
        if "hbm" in text or "high bandwidth" in text:
            return "HBM 认证与产能"
        if "nand" in text or "dram" in text or "pricing" in text or "price" in text or "shortage" in text or "supercycle" in text:
            return "存储价格与周期"
        if "advanced packaging" in text or "soic" in text or "emib" in text or "3d stacked" in text or "先进封装" in text:
            return "先进封装与 3D 存储"
        if "ssd" in text or "dob" in text or "marvell" in text or "storage controller" in text:
            return "企业级存储与控制器"
        if "supply" in text or "capacity" in text or "产能" in text:
            return "供应链压力"
        return (events[-1].get("title") if events else thread_id) or "已跟踪主线"

    def lead_event_for_theme(self, theme: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {}
        theme_tokens = {
            "HBM 认证与产能": ("hbm", "high bandwidth", "英伟达", "nvidia"),
            "中国存储扩张": ("cxmt", "ymtc", "长鑫", "长存", "中国存储"),
            "存储价格与周期": ("dram", "nand", "价格", "供需", "shortage", "supercycle", "pricing", "price"),
            "先进封装与 3D 存储": ("advanced packaging", "soic", "emib", "3d", "先进封装"),
            "企业级存储与控制器": ("ssd", "dob", "marvell", "控制器"),
        }.get(theme, ())
        if theme_tokens:
            matches = [
                event for event in events
                if any(token in (event.get("title") or "").lower() for token in theme_tokens)
            ]
            if matches:
                return self.lead_event(matches)
        return self.lead_event(events)

    def lead_event(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        return sorted(events, key=self.event_sort_key)[0] if events else {}

    def event_sort_key(self, event: dict[str, Any]) -> tuple:
        return (
            self.title_language_penalty(event.get("title") or ""),
            int(event.get("priority") or 999),
            event.get("date") or "",
        )

    def title_language_penalty(self, title: str) -> int:
        return 0 if re.search(r"[\u4e00-\u9fff]", title) else 1

    def unique_flatten(self, events: list[dict[str, Any]], field: str) -> list[str]:
        values = []
        for event in events:
            current = event.get(field) or []
            if isinstance(current, str):
                try:
                    current = json.loads(current)
                except json.JSONDecodeError:
                    current = []
            for value in current:
                if value and value not in values:
                    values.append(str(value))
        return values

    def lowest_confidence(self, events: list[dict[str, Any]]) -> str:
        rank = {"A": 0, "B": 1, "C": 2}
        value = max((event.get("confidence") or "B" for event in events), key=lambda item: rank.get(item, 1))
        return value if value in rank else "B"

    def slug(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")

    def report_topic_key(self, event: dict[str, Any]) -> str:
        title_text = (event.get("title") or "").lower()
        if any(token in title_text for token in ("cxmt", "ymtc", "长鑫", "长存", "中国存储")):
            return "topic-china-memory"
        if any(token in title_text for token in ("hbm", "high bandwidth", "nvidia")):
            return "topic-hbm"
        if any(token in title_text for token in ("dram", "nand", "pricing", "price", "shortage", "supercycle", "upcycle", "价格", "供需")):
            return "topic-memory-cycle"
        if any(token in title_text for token in ("advanced packaging", "soic", "emib", "3d stacked", "先进封装")):
            return "topic-packaging"
        if any(token in title_text for token in ("ssd", "dob", "marvell", "storage controller", "控制器")):
            return "topic-enterprise-storage"

        text = " ".join([
            event.get("thread_id") or "",
            event.get("title") or "",
            " ".join(str(value) for value in self.json_list(event.get("term_ids"))),
            " ".join(str(value) for value in self.json_list(event.get("entity_ids"))),
        ]).lower()
        if any(token in text for token in ("cxmt", "ymtc", "长鑫", "长存", "中国存储")):
            return "topic-china-memory"
        if any(token in text for token in ("hbm", "high bandwidth", "nvidia")):
            return "topic-hbm"
        if any(token in text for token in ("dram", "nand", "pricing", "price", "shortage", "supercycle", "upcycle")):
            return "topic-memory-cycle"
        if any(token in text for token in ("advanced packaging", "soic", "emib", "3d stacked", "先进封装")):
            return "topic-packaging"
        if any(token in text for token in ("ssd", "dob", "marvell", "storage controller")):
            return "topic-enterprise-storage"
        return event.get("thread_id") or "topic-unknown"

    def json_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []
