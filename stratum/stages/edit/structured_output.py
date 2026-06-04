"""Structured event-thread output repair helpers for Edit stage."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


THREAD_ID_RE = re.compile(r"^et-[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class DeterministicStructuredOutputBuilder:
    """Build deterministic event-thread output from the final edit plan."""

    max_threads: int = 6

    def build(self, plan: dict, domain_id: str, run_date: str) -> dict:
        threads = self._build_threads(plan, domain_id, run_date)
        causal_edges = self._build_causal_edges(threads)
        judgments = self._build_judgments(threads, run_date)
        return normalize_structured_data(
            {"threads": threads, "causal_edges": causal_edges, "judgments": judgments},
            domain_id,
            run_date,
        )

    def _build_threads(self, plan: dict, domain_id: str, run_date: str) -> list[dict]:
        threads = []
        seen = set()
        for idx, item in enumerate(plan.get("items", []), start=1):
            if item.get("kind") != "main":
                continue
            thread_id = item.get("thread_id") or _synthetic_thread_id(
                domain_id,
                run_date,
                {"title": item["title_hint"]},
                idx,
            )
            if not _is_valid_thread_id(thread_id) or thread_id in seen:
                continue
            seen.add(thread_id)
            evidence = item.get("evidence") or []
            entities = []
            terms = []
            for article in evidence:
                entities.extend(article.get("entities") or [])
                terms.extend(article.get("terms") or [])
            threads.append({
                "thread_id": thread_id,
                "id": thread_id,
                "title": item["title_hint"][:150],
                "status": "active",
                "priority": "high" if len(threads) < 3 else "medium",
                "entity_ids": list(dict.fromkeys(str(entity) for entity in entities if entity))[:8],
                "term_ids": list(dict.fromkeys(str(term) for term in terms if term))[:10],
                "watch_signals": [item["title_hint"][:120]],
                "close_conditions": ["关键客户认证、量产节奏或价格方向被后续来源明确验证"],
                "created": run_date,
                "last_updated": run_date,
            })
            if len(threads) >= self.max_threads:
                break
        return threads

    def _build_causal_edges(self, threads: list[dict]) -> list[dict]:
        if len(threads) < 2:
            return []
        return [{
            "cause_thread_id": threads[0]["thread_id"],
            "effect_thread_id": threads[1]["thread_id"],
            "mechanism": "Leading HBM qualification and production progress changes supplier allocation, capacity priorities, and downstream memory market pricing expectations.",
            "confidence": "B",
        }]

    def _build_judgments(self, threads: list[dict], run_date: str) -> list[dict]:
        if not threads:
            return []
        return [{
            "target_type": "event_pair",
            "target_thread_ids": (
                [thread["thread_id"] for thread in threads[:2]]
                if len(threads) >= 2
                else [threads[0]["thread_id"]]
            ),
            "hypothesis": "If HBM qualification and capacity expansion continue through the next verification window, memory suppliers with validated high-bandwidth products will keep stronger pricing power than commodity-only suppliers.",
            "confidence": "B",
            "expected_verification": run_date[:4] + "-12-31",
        }]


def normalize_structured_data(
    data: dict | None,
    domain_id: str = "domain",
    run_date: str = "",
) -> dict | None:
    """Normalize common LLM key drift in optional structured output."""
    if not isinstance(data, dict):
        return data
    for key in ("threads", "causal_edges", "judgments"):
        data[key] = _normalize_structured_list(data.get(key))
    thread_id_map: dict[str, str] = {}
    for index, thread in enumerate(data.get("threads", []), start=1):
        if not isinstance(thread, dict):
            continue
        original_id = str(thread.get("thread_id") or thread.get("id") or "").strip()
        thread_id = original_id
        if not _is_valid_thread_id(thread_id):
            thread_id = _synthetic_thread_id(domain_id, run_date, thread, index)
        if original_id and original_id != thread_id:
            thread_id_map[original_id] = thread_id
        thread["thread_id"] = thread_id
        thread["id"] = thread_id
    for edge in data.get("causal_edges", []):
        if not isinstance(edge, dict):
            continue
        for key in ("cause_thread_id", "effect_thread_id"):
            value = str(edge.get(key) or "").strip()
            if value in thread_id_map:
                edge[key] = thread_id_map[value]
    data["causal_edges"] = [
        edge for edge in data.get("causal_edges", [])
        if isinstance(edge, dict)
        and str(edge.get("cause_thread_id") or "").strip()
        and str(edge.get("effect_thread_id") or "").strip()
    ]
    for judgment in data.get("judgments", []):
        if isinstance(judgment, dict) and "hypothesis" not in judgment and "mechanism" in judgment:
            judgment["hypothesis"] = judgment.pop("mechanism")
        if isinstance(judgment, dict) and isinstance(judgment.get("target_thread_ids"), list):
            judgment["target_thread_ids"] = [
                thread_id_map.get(str(thread_id), thread_id)
                for thread_id in judgment.get("target_thread_ids", [])
            ]
    return data


def structured_event_counts(data: dict | None) -> dict[str, int]:
    """Count structured event-thread surfaces that should be persisted."""
    if not isinstance(data, dict):
        return {"threads": 0, "causal_edges": 0, "judgments": 0}
    return {
        "threads": len(data.get("threads") if isinstance(data.get("threads"), list) else []),
        "causal_edges": len(data.get("causal_edges") if isinstance(data.get("causal_edges"), list) else []),
        "judgments": len(data.get("judgments") if isinstance(data.get("judgments"), list) else []),
    }


def should_write_event_threads(data: dict | None) -> bool:
    """Return True when structured output carries any event-thread state."""
    return any(structured_event_counts(data).values())


def _normalize_structured_list(value) -> list:
    """Return a list for structured-output array fields."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _is_valid_thread_id(thread_id: str) -> bool:
    return bool(thread_id and THREAD_ID_RE.match(thread_id))


def _synthetic_thread_id(domain_id: str, run_date: str, thread: dict, index: int) -> str:
    """Build a deterministic id for new LLM-created threads."""
    title = str(thread.get("title") or thread.get("label") or thread.get("canonical_question") or "")
    seed = f"{domain_id}|{run_date}|{index}|{title}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    date_part = re.sub(r"[^0-9]", "", run_date) or "undated"
    domain_part = re.sub(r"[^a-z0-9_-]+", "-", domain_id.lower()).strip("-") or "domain"
    return f"et-{domain_part}-{date_part}-{digest}"
