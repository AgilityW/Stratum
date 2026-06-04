"""Thread keyword matching algorithms for Normalize."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThreadMatchDecision:
    """Best thread match for one article."""

    thread_id: str | None
    matched_tokens: list[str] = field(default_factory=list)
    score: float = 0.0


class ThreadKeywordMatcher:
    """Match article text against active event-thread keyword fingerprints."""

    def __init__(self, thread_keywords: dict | None = None):
        self.thread_keywords = thread_keywords or {"threads": []}
        self.threads = self.thread_keywords.get("threads", [])
        self.keyword_thread_count = self._keyword_thread_counts()

    def match(self, title: str, snippet: str) -> ThreadMatchDecision:
        text = f"{title} {snippet}".lower()
        best = ThreadMatchDecision(thread_id=None)

        for thread in self.threads:
            score, strong_signals, matched_kw_count, matched_tokens = self._score_thread(thread, text)
            if matched_kw_count >= 2:
                score += (matched_kw_count - 1) * 2
                strong_signals = max(strong_signals, 1)

            threshold = 3 if strong_signals > 0 else 4
            if score >= threshold and score > best.score:
                best = ThreadMatchDecision(
                    thread_id=thread.get("thread_id"),
                    matched_tokens=list(dict.fromkeys(matched_tokens)),
                    score=score,
                )

        return best

    def match_tuple(self, title: str, snippet: str) -> tuple[str | None, list[str]]:
        decision = self.match(title, snippet)
        return decision.thread_id, decision.matched_tokens

    def _keyword_thread_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for thread in self.threads:
            seen_in_thread = set()
            for kw in thread.get("keywords", []):
                keyword = kw.lower().strip()
                if keyword and keyword not in seen_in_thread:
                    counts[keyword] = counts.get(keyword, 0) + 1
                    seen_in_thread.add(keyword)
        return counts

    def idf_weight(self, keyword: str) -> float:
        count = self.keyword_thread_count.get(keyword, 1)
        if count == 1:
            return 2.0
        if count <= 3:
            return 1.0
        return 0.5

    def _score_thread(self, thread: dict, text: str) -> tuple[float, int, int, list[str]]:
        keywords = [k.lower().strip() for k in thread.get("keywords", []) if k.strip()]
        topics = [t.lower().strip() for t in thread.get("topics", []) if t.strip()]
        score = 0.0
        strong_signals = 0
        matched_kw_count = 0
        matched_tokens = []

        for keyword in keywords:
            if len(keyword) >= 2 and keyword in text:
                weight = self.idf_weight(keyword)
                score += 3 * weight
                matched_kw_count += 1
                matched_tokens.append(keyword)
                if weight >= 2.0:
                    strong_signals += 1

        for topic in topics:
            if len(topic) >= 2 and topic in text:
                score += 2 * self.idf_weight(topic)
                strong_signals += 1
                matched_tokens.append(topic)

        score, strong_signals, matched_kw_count = self._score_ascii_subtokens(
            keywords, text, score, strong_signals, matched_kw_count, matched_tokens
        )
        score = self._score_cjk_subtokens(keywords, text, score)
        return score, strong_signals, matched_kw_count, matched_tokens

    def _score_ascii_subtokens(
        self,
        keywords: list[str],
        text: str,
        score: float,
        strong_signals: int,
        matched_kw_count: int,
        matched_tokens: list[str],
    ) -> tuple[float, int, int]:
        keyword_text = " ".join(keywords)
        ascii_words = re.findall(r"[A-Za-z0-9]{2,}", keyword_text)
        seen_ascii = set(keyword.lower() for keyword in keywords if keyword.isascii())
        for word in ascii_words:
            lowered = word.lower()
            if lowered not in seen_ascii and lowered in text:
                score += 2
                strong_signals += 1
                matched_kw_count += 1
                matched_tokens.append(lowered)
        return score, strong_signals, matched_kw_count

    def _score_cjk_subtokens(self, keywords: list[str], text: str, score: float) -> float:
        cjk_seen = set()
        for keyword in keywords:
            cjk_chars = re.findall(r"[\u4e00-\u9fff]", keyword)
            if len(cjk_chars) <= 2:
                continue
            for window_size in (2, 3, 4):
                for index in range(len(cjk_chars) - window_size + 1):
                    token = "".join(cjk_chars[index:index + window_size])
                    if token not in cjk_seen and len(token) >= 2 and token in text:
                        score += 1
                        cjk_seen.add(token)
        return score


def match_thread_keywords(title: str, snippet: str, thread_keywords: dict) -> tuple[str | None, list[str]]:
    """Compatibility wrapper for existing Normalize callers."""
    return ThreadKeywordMatcher(thread_keywords).match_tuple(title, snippet)

