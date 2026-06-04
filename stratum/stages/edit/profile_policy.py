"""Profile polish policy for Edit stage report-level sections."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ProfilePolishPolicy:
    """Normalize report-level summary, focus, and contrarian sections."""

    summary_target: int = 2
    focus_target: int = 3
    contrarian_target: int = 3

    def user_payload(self, titles: list[str]) -> dict:
        return {
            "titles": titles,
            "items": [
                {
                    "title": title,
                    "kind": "edge" if title.startswith("【边缘信号】") else "main",
                }
                for title in titles
            ],
        }

    def normalize_sections(self, parsed: dict | None, titles: list[str]) -> dict:
        if not isinstance(parsed, dict):
            parsed = {}
        summary = self._clean_list(parsed.get("summary"), self.summary_target, self.fallback_summary(titles))
        focus = self._clean_list(parsed.get("focus"), self.focus_target, self.fallback_focus(titles))
        contrarian = self._clean_list(
            parsed.get("contrarian"),
            self.contrarian_target,
            self.fallback_contrarian(titles),
        )
        return {
            "summary": summary[:self.summary_target],
            "focus": focus[:self.focus_target],
            "contrarian": contrarian[:self.contrarian_target],
        }

    def deterministic_sections(self, items: list[dict], omitted_candidates: list[dict] | None = None) -> dict:
        """Build summary/focus/contrarian sections from selected validated items."""
        omitted_candidates = omitted_candidates or []
        main_items = [item for item in items if item.get("kind") != "edge"]
        edge_items = [item for item in items if item.get("kind") == "edge"]
        main_titles = [self._title(item) for item in main_items if self._title(item)]
        edge_titles = [self._title(item, strip_edge=True) for item in edge_items if self._title(item, strip_edge=True)]

        summary = self._deterministic_summary(main_titles, len(edge_titles))
        focus = self._deterministic_focus(main_titles)
        contrarian = self._deterministic_contrarian(edge_titles, omitted_candidates)
        return {
            "summary": summary[:self.summary_target],
            "focus": focus[:self.focus_target],
            "contrarian": contrarian[:self.contrarian_target],
        }

    def fallback_summary(self, titles: list[str]) -> list[str]:
        main = [title for title in titles if not title.startswith("【边缘信号】")]
        edge = [title for title in titles if title.startswith("【边缘信号】")]
        return [
            f"今日存储主线集中在 {main[0] if main else 'HBM、价格与产能'} 等议题，供需紧张和 AI 需求仍是主要驱动。",
            f"同时有 {len(edge)} 条边缘信号进入观察池，用于追踪尚未形成主线判断的产业链变量。",
        ]

    def fallback_focus(self, titles: list[str]) -> list[str]:
        return [
            "HBM4/HBM4E 的客户认证、良率和量产节奏是否继续兑现。",
            "DRAM/NAND 价格上涨是否从供给短缺转向终端需求破坏。",
            "中国存储厂商的 IPO、客户导入和产能扩张是否出现可验证进展。",
        ]

    def fallback_contrarian(self, titles: list[str]) -> list[str]:
        return [
            "高价格可能抑制 PC、消费电子和部分云客户需求，削弱超级周期斜率。",
            "HBM 产能扩张若快于客户认证节奏，可能造成局部供需错配。",
            "部分边缘技术和个股信号仍缺少量产、订单或客户认证支撑。",
        ]

    def _clean_list(self, value, target: int, fallback: list[str]) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            value = []
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        cleaned.extend(fallback)
        return cleaned[:target]

    def _title(self, item: dict, strip_edge: bool = False) -> str:
        title = str(item.get("title_hint") or item.get("title") or "").strip()
        if strip_edge:
            title = re.sub(r"^【边缘信号】", "", title).strip()
        return title

    def _deterministic_summary(self, main_titles: list[str], edge_count: int) -> list[str]:
        if not main_titles:
            return self.fallback_summary([])
        summary = [f"今日主线集中在 {main_titles[0]}。"]
        if len(main_titles) > 1:
            summary.append(f"同时，{main_titles[1]} 也是需要持续跟踪的核心变量。")
        elif edge_count:
            summary.append(f"另有 {edge_count} 条边缘信号进入观察池，用于补充主线之外的产业变量。")
        else:
            summary.append("当前成稿以高证据密度主条目为主，边缘信号占比较低。")
        return summary

    def _deterministic_focus(self, main_titles: list[str]) -> list[str]:
        if not main_titles:
            return self.fallback_focus([])
        return [self._to_focus_bullet(title) for title in main_titles[:self.focus_target]]

    def _deterministic_contrarian(self, edge_titles: list[str], omitted_candidates: list[dict]) -> list[str]:
        contrarian = [f"{title} 仍需更多交叉来源验证。" for title in edge_titles[:self.contrarian_target]]
        for candidate in omitted_candidates:
            if len(contrarian) >= self.contrarian_target:
                break
            title = str(candidate.get("title") or "").strip()
            reason = str(candidate.get("reason") or "").strip()
            if title:
                contrarian.append(f"{title} 暂未进入主线，原因是 {reason}。")
        if not contrarian:
            return self.fallback_contrarian([])
        return contrarian[:self.contrarian_target]

    def _to_focus_bullet(self, title: str) -> str:
        title = str(title).strip().rstrip("。")
        return title[:80] if title else "核心主线仍需持续验证。"
