"""Domain keyword extraction and admission scoring for watchlist acquisition.

Reads companies and terms from domain.yaml, returns a flat lowercase
keyword list used for article filtering in RSS, direct_fetch, and browser
watchlist.

Domain-scoped: each domain.yaml defines its own keywords.
Storage keywords ≠ robot keywords.
"""

import os
from dataclasses import dataclass
import yaml


WEAK_SIGNAL_TERMS = (
    "advanced packaging",
    "ai accelerator",
    "bandwidth",
    "chiplet",
    "controller",
    "cxl",
    "ddr",
    "dram",
    "flash",
    "gpu",
    "hbm",
    "memory",
    "nand",
    "nvme",
    "pcie",
    "semiconductor",
    "ssd",
    "storage",
    "substrate",
    "wafer",
    "封装",
    "存储",
    "記憶體",
    "メモリ",
    "半導体",
    "반도체",
    "메모리",
)

OFFICIAL_SOURCE_TYPES = {"official", "analyst"}
ACCEPT_SCORE = 1.0
WEAK_SIGNAL_SCORE = 0.55


@dataclass(frozen=True)
class AdmissionDecision:
    """Watchlist candidate admission decision."""

    status: str  # accept | weak_signal | reject
    score: float
    matched_keywords: tuple[str, ...]
    reason: str

    @property
    def accepted(self) -> bool:
        return self.status in {"accept", "weak_signal"}


def load_keywords(domain: str, workspace: str) -> list[str]:
    """Extract normalized keywords from domain.yaml.
    
    Sources:
    - companies.*.aliases.*  → all locale names (en, zh-CN, ja...)
    - terms.*.aliases.*      → all locale names
    - terms.*.id             → term IDs as fallback
    
    Returns: Lowercase, deduplicated, longest-first sorted list.
    """
    path = os.path.join(workspace, "domains", domain, "domain.yaml")
    if not os.path.exists(path):
        return []

    with open(path) as f:
        data = yaml.safe_load(f)

    keywords: set[str] = set()

    # Company names (all locales)
    for comp in data.get("companies", []):
        for name in comp.get("aliases", {}).values():
            if name:
                keywords.add(name.lower())

    # Technology terms
    for term in data.get("terms", []):
        for name in term.get("aliases", {}).values():
            if name:
                keywords.add(name.lower())
        tid = term.get("id", "")
        if tid:
            keywords.add(tid.lower())

    # Filter: remove very short/noisy keywords
    filtered = {k for k in keywords if len(k) >= 3}
    # Longest first — enables greedy matching
    return sorted(filtered, key=len, reverse=True)


def match_keywords(title: str, snippet: str, keywords: list[str]) -> bool:
    """Check if article text matches any domain keyword.
    
    Longest-first to prioritize specific terms (e.g., 'sk hynix' 
    before 'hynix'). Skip if keywords list is empty (pass-through mode).
    """
    if not keywords:
        return True

    text = f"{title} {snippet}".lower()
    for kw in keywords:
        if kw in text:
            return True
    return False


def admission_decision(
    title: str,
    snippet: str,
    keywords: list[str],
    *,
    source_type: str = "",
    published_at: str | None = None,
) -> AdmissionDecision:
    """Score a watchlist candidate before admitting it to raw evidence.

    Hard keyword matching is too brittle for broad RSS feeds. This decision keeps
    exact domain keyword hits as strong accepts while allowing lower-confidence
    storage-sector weak signals through for downstream verification.
    """
    if not keywords:
        return AdmissionDecision("accept", 1.0, (), "no domain keywords configured")

    text = f"{title} {snippet}".lower()
    exact_matches = tuple(kw for kw in keywords if kw in text)
    weak_matches = tuple(term for term in WEAK_SIGNAL_TERMS if term in text)
    score = 0.0

    if exact_matches:
        score += 1.0 + min(len(exact_matches) - 1, 3) * 0.1
    if weak_matches:
        score += 0.55 + min(len(weak_matches) - 1, 3) * 0.05
    if source_type in OFFICIAL_SOURCE_TYPES:
        score += 0.25
    if published_at:
        score += 0.1

    score = round(min(score, 1.5), 3)
    if exact_matches or score >= ACCEPT_SCORE:
        return AdmissionDecision(
            "accept",
            score,
            exact_matches or weak_matches,
            "domain keyword match" if exact_matches else "trusted source weak signal",
        )
    if weak_matches and score >= WEAK_SIGNAL_SCORE:
        return AdmissionDecision(
            "weak_signal",
            score,
            weak_matches,
            "storage-sector weak signal",
        )
    return AdmissionDecision("reject", score, (), "no domain or weak-signal match")


def admit_result(result, keywords: list[str]):
    """Apply admission scoring to a SearchResult-like object."""
    decision = admission_decision(
        getattr(result, "title", ""),
        getattr(result, "snippet", ""),
        keywords,
        source_type=getattr(result, "source_type_hint", ""),
        published_at=getattr(result, "published_at", None),
    )
    if decision.accepted:
        result.score = max(float(getattr(result, "score", 0.0) or 0.0), decision.score)
        result.query_dimension = decision.status
        return result
    return None


def candidate_record(result, decision: AdmissionDecision, *, source_id: str = "", access: str = "") -> dict:
    """Build an auditable watchlist candidate admission record."""
    return {
        "source": source_id,
        "access": access,
        "url": getattr(result, "url", ""),
        "title": getattr(result, "title", ""),
        "snippet": getattr(result, "snippet", ""),
        "locale": getattr(result, "locale", ""),
        "published_at": getattr(result, "published_at", None),
        "source_domain": getattr(result, "source_domain", ""),
        "source_type_hint": getattr(result, "source_type_hint", ""),
        "engine": getattr(result, "engine", ""),
        "query_id": getattr(result, "query_id", ""),
        "status": decision.status,
        "accepted": decision.accepted,
        "score": decision.score,
        "matched_keywords": list(decision.matched_keywords),
        "reason": decision.reason,
    }


def admit_results_with_candidates(
    results: list,
    keywords: list[str],
    *,
    source_id: str = "",
    access: str = "",
) -> tuple[list, list[dict]]:
    """Return admitted results and all admission candidate records."""
    admitted = []
    candidates = []
    for result in results:
        decision = admission_decision(
            getattr(result, "title", ""),
            getattr(result, "snippet", ""),
            keywords,
            source_type=getattr(result, "source_type_hint", ""),
            published_at=getattr(result, "published_at", None),
        )
        candidates.append(candidate_record(result, decision, source_id=source_id, access=access))
        if decision.accepted:
            result.score = max(float(getattr(result, "score", 0.0) or 0.0), decision.score)
            result.query_dimension = decision.status
            admitted.append(result)
    return admitted, candidates


def admit_results(results: list, keywords: list[str]) -> list:
    """Return results admitted by the shared watchlist admission scorer."""
    admitted, _candidates = admit_results_with_candidates(results, keywords)
    return admitted
