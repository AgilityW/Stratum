"""Story-tracking repository layer — persistent storage for events, causal edges, judgments.

Repository pattern: all business logic depends on ABCs.
Current implementation: JSONL-backed.
Future: swap to SQLite by implementing the same ABCs.

Storage layout (per domain):
  {base_path}/
    events.jsonl
    causal.jsonl
    judgments.jsonl
    state.json          — {next_event_seq, next_causal_seq, next_judgment_seq, last_write}
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from story_contracts import EventRecord, CausalEdge, Judgment, to_jsonl_line


# ═══════════════════════════════════════════════════
# State Manager
# ═══════════════════════════════════════════════════

class StateManager:
    """Manages sequence counters and metadata for a domain's story-tracking storage."""

    def __init__(self, base_path: str):
        self.base_path = base_path
        self._state_path = os.path.join(base_path, "state.json")
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(self.base_path, exist_ok=True)

    def _read_state(self) -> dict:
        if not os.path.exists(self._state_path):
            return {"next_event_seq": 1, "next_causal_seq": 1, "next_judgment_seq": 1}
        with open(self._state_path, "r") as f:
            return json.load(f)

    def _write_state(self, state: dict):
        state["last_write"] = datetime.now().isoformat()
        with open(self._state_path, "w") as f:
            json.dump(state, f, indent=2)

    def next_event_seq(self) -> int:
        state = self._read_state()
        seq = state["next_event_seq"]
        state["next_event_seq"] = seq + 1
        self._write_state(state)
        return seq

    def next_causal_seq(self) -> int:
        state = self._read_state()
        seq = state["next_causal_seq"]
        state["next_causal_seq"] = seq + 1
        self._write_state(state)
        return seq

    def next_judgment_seq(self) -> int:
        state = self._read_state()
        seq = state["next_judgment_seq"]
        state["next_judgment_seq"] = seq + 1
        self._write_state(state)
        return seq

    def get_state(self) -> dict:
        return self._read_state()


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


class JsonlEventRepository(EventRepository):
    """JSONL-backed event storage. One EventRecord per line."""

    def __init__(self, base_path: str, domain_id: str):
        self.base_path = base_path
        self.domain_id = domain_id
        self._file_path = os.path.join(base_path, "events.jsonl")
        self._state = StateManager(base_path)
        os.makedirs(base_path, exist_ok=True)

    def add(self, event: EventRecord) -> None:
        line = to_jsonl_line(event)
        with open(self._file_path, "a") as f:
            f.write(line + "\n")

    def get(self, event_id: str) -> Optional[EventRecord]:
        if not os.path.exists(self._file_path):
            return None
        with open(self._file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("id") == event_id:
                    return self._deserialize(data)
        return None

    def update(self, event: EventRecord) -> None:
        """Update an existing event by deleting old record and appending new one."""
        if not os.path.exists(self._file_path):
            raise ValueError(f"Event {event.id} not found — storage is empty")
        records = self.all()
        found = False
        with open(self._file_path, "w") as f:
            for record in records:
                if record.id == event.id:
                    f.write(to_jsonl_line(event) + "\n")
                    found = True
                else:
                    f.write(to_jsonl_line(record) + "\n")
        if not found:
            raise ValueError(f"Event {event.id} not found for update")

    def all(self) -> list[EventRecord]:
        if not os.path.exists(self._file_path):
            return []
        records = []
        with open(self._file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                records.append(self._deserialize(data))
        return records

    def count(self) -> int:
        return len(self.all())

    @staticmethod
    def _deserialize(data: dict) -> EventRecord:
        return EventRecord(**data)


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


class JsonlCausalRepository(CausalRepository):
    """JSONL-backed causal edge storage."""

    def __init__(self, base_path: str):
        self._file_path = os.path.join(base_path, "causal.jsonl")
        os.makedirs(base_path, exist_ok=True)

    def add(self, edge: CausalEdge) -> None:
        line = to_jsonl_line(edge)
        with open(self._file_path, "a") as f:
            f.write(line + "\n")

    def get(self, edge_id: str) -> Optional[CausalEdge]:
        for edge in self.all():
            if edge.id == edge_id:
                return edge
        return None

    def all(self) -> list[CausalEdge]:
        return self._read_all()

    def find_by_cause(self, cause_id: str) -> list[CausalEdge]:
        return [e for e in self.all() if e.cause_id == cause_id]

    def find_by_effect(self, effect_id: str) -> list[CausalEdge]:
        return [e for e in self.all() if e.effect_id == effect_id]

    def _read_all(self) -> list[CausalEdge]:
        if not os.path.exists(self._file_path):
            return []
        edges = []
        with open(self._file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                edges.append(CausalEdge(**data))
        return edges

    def count(self) -> int:
        return len(self._read_all())


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


class JsonlJudgmentRepository(JudgmentRepository):
    """JSONL-backed judgment storage."""

    def __init__(self, base_path: str):
        self._file_path = os.path.join(base_path, "judgments.jsonl")
        os.makedirs(base_path, exist_ok=True)

    def add(self, judgment: Judgment) -> None:
        line = to_jsonl_line(judgment)
        with open(self._file_path, "a") as f:
            f.write(line + "\n")

    def get(self, judgment_id: str) -> Optional[Judgment]:
        for j in self.all():
            if j.id == judgment_id:
                return j
        return None

    def update(self, judgment: Judgment) -> None:
        records = self.all()
        found = False
        with open(self._file_path, "w") as f:
            for record in records:
                if record.id == judgment.id:
                    f.write(to_jsonl_line(judgment) + "\n")
                    found = True
                else:
                    f.write(to_jsonl_line(record) + "\n")
        if not found:
            raise ValueError(f"Judgment {judgment.id} not found for update")

    def all(self) -> list[Judgment]:
        if not os.path.exists(self._file_path):
            return []
        judgments = []
        with open(self._file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                judgments.append(Judgment(**data))
        return judgments

    def find_by_verdict(self, verdict: str) -> list[Judgment]:
        return [j for j in self.all() if j.verdict == verdict]

    def count(self) -> int:
        return len(self.all())
