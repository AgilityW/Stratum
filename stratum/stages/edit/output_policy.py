"""Output policy checks for Edit stage Markdown."""

from __future__ import annotations


NON_NEWS_SECTIONS = {"今日要点", "行业要点", "产业信号", "特别关注", "反向信号"}
EDGE_SIGNAL_KEYWORDS = (
    "anthropic",
    "模型公司",
    "玻璃硬盘",
    "玻璃存储",
    "威刚",
    "创见",
    "模组",
    "董事会",
    "任命",
    "光盘",
)


class EditOutputPolicy:
    """Classify and validate generated Markdown item structure."""

    def markdown_news_titles(self, markdown: str) -> list[str]:
        titles = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith("### "):
                continue
            title = stripped.replace("### ", "", 1).strip()
            if title not in NON_NEWS_SECTIONS:
                titles.append(title)
        return titles

    def normalize_edge_signal_headings(self, markdown: str) -> str:
        """Prefix weak-signal item headings so they stay visually separated."""
        lines = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith("### "):
                lines.append(line)
                continue
            title = stripped.replace("### ", "", 1).strip()
            if title in NON_NEWS_SECTIONS or title.startswith("【边缘信号】"):
                lines.append(line)
                continue
            title_lower = title.lower()
            if any(keyword.lower() in title_lower for keyword in EDGE_SIGNAL_KEYWORDS):
                prefix = line[:len(line) - len(line.lstrip())]
                lines.append(f"{prefix}### 【边缘信号】{title}")
            else:
                lines.append(line)
        return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")

    def item_count_within_budget(self, markdown: str, output_cfg: dict) -> tuple[bool, str]:
        """Check generated news item count against prompt budget."""
        budget = output_cfg.get("_budget", {}) if isinstance(output_cfg, dict) else {}
        plan_counts = output_cfg.get("_plan_counts", {}) if isinstance(output_cfg, dict) else {}
        min_items = int(budget.get("min_items", 0) or 0)
        max_items = int(budget.get("max_items", 0) or 0)
        main_min_items = int(budget.get("main_min_items", 0) or 0)
        main_max_items = int(budget.get("main_max_items", 0) or 0)
        edge_min_items = int(budget.get("edge_min_items", 0) or 0)
        edge_max_items = int(budget.get("edge_max_items", 0) or 0)
        titles = self.markdown_news_titles(markdown)
        count = len(titles)
        edge_count = sum(1 for title in titles if title.startswith("【边缘信号】"))
        main_count = count - edge_count
        if plan_counts:
            min_items = self._evidence_aware_minimum(min_items, int(plan_counts.get("total_items", 0) or 0))
            main_min_items = self._evidence_aware_minimum(main_min_items, int(plan_counts.get("main_items", 0) or 0))
            edge_min_items = self._evidence_aware_minimum(edge_min_items, int(plan_counts.get("edge_items", 0) or 0))
        if min_items and count < min_items:
            return False, f"generated {count} news items; total minimum is {min_items}"
        if max_items and count > max_items:
            return False, f"generated {count} news items; total maximum is {max_items}"
        if main_min_items and main_count < main_min_items:
            return False, f"generated {main_count} main news items; main minimum is {main_min_items}"
        if main_max_items and main_count > main_max_items:
            return False, f"generated {main_count} main news items; main maximum is {main_max_items}"
        if edge_min_items and edge_count < edge_min_items:
            return False, f"generated {edge_count} edge-signal items; edge minimum is {edge_min_items}"
        if edge_max_items and edge_count > edge_max_items:
            return False, f"generated {edge_count} edge-signal items; edge maximum is {edge_max_items}"
        return True, f"generated {count} news items ({main_count} main, {edge_count} edge-signal)"

    def _evidence_aware_minimum(self, configured_minimum: int, planned_items: int) -> int:
        """Lower minimums when the deterministic plan has less valid evidence."""
        if configured_minimum <= 0:
            return 0
        if planned_items <= 0:
            return configured_minimum
        return min(configured_minimum, planned_items)
