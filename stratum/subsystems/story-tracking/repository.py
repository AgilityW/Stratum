"""Story-tracking repository layer — abstract interfaces for event/causal/judgment storage.

Repository pattern: all business logic depends on ABCs.
Current implementation: SQLite-backed (inlined in pipeline.py via stratum.db.connection).
"""

from abc import ABC, abstractmethod
from typing import Optional

from story_contracts import EventRecord, CausalEdge, Judgment


# ═══════════════════════════════════════════════════
# Event Repository
# ═══════════════════════════════════════════════════

class EventRepository(ABC):
    @abstractmethod
    def add(self, event: EventRecord) -> None: ...

    @abstractmethod
    def get(self, event_id: str) -> Optional[EventRecord]: ...

    @abstractmethod
    def update(self, event: EventRecord) -> None: ...

    @abstractmethod
    def all(self) -> list[EventRecord]: ...

    @abstractmethod
    def find_by_thread_id(self, thread_id: str) -> Optional[EventRecord]: ...


# ═══════════════════════════════════════════════════
# Causal Repository
# ═══════════════════════════════════════════════════

class CausalRepository(ABC):
    @abstractmethod
    def add(self, edge: CausalEdge) -> None: ...

    @abstractmethod
    def get(self, edge_id: str) -> Optional[CausalEdge]: ...

    @abstractmethod
    def all(self) -> list[CausalEdge]: ...

    @abstractmethod
    def find_by_cause(self, cause_id: str) -> list[CausalEdge]: ...

    @abstractmethod
    def find_by_effect(self, effect_id: str) -> list[CausalEdge]: ...


# ═══════════════════════════════════════════════════
# Judgment Repository
# ═══════════════════════════════════════════════════

class JudgmentRepository(ABC):
    @abstractmethod
    def add(self, judgment: Judgment) -> None: ...

    @abstractmethod
    def get(self, judgment_id: str) -> Optional[Judgment]: ...

    @abstractmethod
    def update(self, judgment: Judgment) -> None: ...

    @abstractmethod
    def all(self) -> list[Judgment]: ...

    @abstractmethod
    def find_by_verdict(self, verdict: str) -> list[Judgment]: ...
