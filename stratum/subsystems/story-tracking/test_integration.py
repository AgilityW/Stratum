"""Integration test — full story-tracking loop.

Simulates the end-to-end flow:
  1. Agent produces event-threads.json (sample data matching real format)
  2. Story Bridge ingests into EventStore
  3. Events are queryable by topic, entity, date, scale
  4. BriefingContext is generated for the next day
  5. Context correctly carries forward events from previous briefing

Tests the full chain: bridge → query → context.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "orchestrator"))
import tempfile
import json
import pytest
import yaml

from story_contracts import EventRecord
from repository import (
    JsonlEventRepository, JsonlCausalRepository, JsonlJudgmentRepository,
    StateManager,
)
from taxonomy import Taxonomy
from query import query_events, events_by_topic, events_by_entity
from briefing_context import generate_context, format_context_for_prompt
from story_bridge import ingest_batch


# ── Sample data matching real event-threads.json format ──

@pytest.fixture
def agent_event_threads():
    """Mimics Agent-produced event-threads.json with 3 real-looking threads."""
    return {
        "version": "1.0",
        "generated": "2026-05-28T15:47:00+08:00",
        "threads": [
            {
                "id": "et-2026-001",
                "title": "Samsung HBM4量产供货NVIDIA",
                "canonical_question": "Samsung HBM4量产对HBM市场竞争格局的影响？",
                "status": "active",
                "priority": 1,
                "parent_cluster_ids": ["sc-2026-05-28-001"],
                "created": "2026-05-28",
                "last_updated": "2026-05-28",
                "timeline": [
                    {"date": "2026-05-27", "event": "Samsung宣布HBM4开始量产供货",
                     "source_cluster": "sc-2026-05-28-001",
                     "significance": "Samsung成为第二家量产HBM4的厂商"},
                ],
                "current_assessment": "Samsung HBM4量产标志着HBM市场从SK Hynix独占进入双雄格局。NVIDIA作为最大客户将获得第二供应商，短期利好NVIDIA，中期可能压缩HBM溢价。",
                "open_questions": ["SK Hynix HBM4产能能否满足NVIDIA全部需求？",
                                  "Micron HBM4时间表是否会加速？"],
                "watch_signals": ["NVIDIA HBM4供应商分配比例",
                                 "SK Hynix HBM4降价应对"]
            },
            {
                "id": "et-2026-002",
                "title": "NAND合约价Q2上涨5%",
                "canonical_question": "NAND价格回暖是结构性还是周期性的？",
                "status": "active",
                "priority": 2,
                "parent_cluster_ids": ["sc-2026-05-28-005"],
                "created": "2026-05-28",
                "last_updated": "2026-05-28",
                "timeline": [
                    {"date": "2026-05-26", "event": "TrendForce报告NAND合约价Q2环比+5%",
                     "source_cluster": "sc-2026-05-28-005",
                     "significance": "NAND价格连续两个季度上涨，供需改善信号"}
                ],
                "current_assessment": "NAND价格回暖主要受原厂主动减产和AI存储需求拉动。三星/铠侠/WDC均将部分NAND产能转为HBM/DRAM。但YMTC产能扩张可能在2027年打破平衡。",
                "open_questions": ["原厂Q3是否会恢复NAND产能？", "YMTC Fab3量产进度？"],
                "watch_signals": ["三星NAND产能分配变化", "NAND现货价波动"]
            },
            {
                "id": "et-2026-003",
                "title": "CXMT DDR5进入海盗船消费级产品",
                "canonical_question": "CXMT DDR5进入全球供应链对DRAM定价的影响？",
                "status": "emerging",
                "priority": 2,
                "parent_cluster_ids": [],
                "created": "2026-05-28",
                "last_updated": "2026-05-28",
                "timeline": [
                    {"date": "2026-05-27", "event": "海盗船发布首款搭载CXMT DDR5颗粒的消费级内存",
                     "source_cluster": None,
                     "significance": "CXMT DDR5首次进入全球零售渠道，获得第三方验证"}
                ],
                "current_assessment": "CXMT DDR5通过海盗船进入消费级市场是标志性事件。虽然初期频率仅6400MT/s，落后三星/SK Hynix的8000+，但标志着中国DRAM从企业级/白牌向品牌消费级扩展。",
                "open_questions": ["海盗船之后哪些品牌会采用CXMT？",
                                  "CXMT DDR5产能能否支撑大规模零售？"],
                "watch_signals": ["金士顿/威刚是否采用CXMT DDR5",
                                 "CXMT DDR5频率提升路线图"]
            }
        ],
        "causal_edges": [
            {
                "cause_thread_id": "et-2026-003",
                "effect_thread_id": "et-2026-001",
                "mechanism": "CXMT DDR5进入消费市场 → 对三星DRAM ASP形成下行压力 → 三星加速HBM4量产以维持ASP",
                "confidence": "B",
            },
        ],
        "judgments": [
            {
                "target_type": "entity",
                "target_entity_ids": ["cxmt"],
                "hypothesis": "CXMT将在3个月内获得至少2家一线OEM的DDR5验证通过",
                "confidence": "B",
                "expected_verification": "2026-08-28",
            },
            {
                "target_type": "event_pair",
                "target_thread_ids": ["et-2026-003", "et-2026-001"],
                "hypothesis": "CXMT DDR5进入零售渠道后6个月内，三星DRAM ASP将下降≥5%，加速HBM产能转换",
                "confidence": "C",
                "expected_verification": "2026-11-28",
            },
        ],
    }


# ── Taxonomy fixture (must match the tags in sample data) ──

@pytest.fixture
def taxonomy_path():
    data = {
        "topics": [
            {"id": "hbm", "aliases": ["HBM4", "HBM3E", "HBM"]},
            {"id": "nand", "aliases": ["NAND", "NAND Flash", "3D NAND"]},
            {"id": "ddr5", "aliases": ["DDR5", "DDR5 SDRAM"]},
            {"id": "pricing", "aliases": ["price", "pricing", "ASP", "contract price"]},
        ],
        "entities": [
            {"id": "samsung", "type": "company",
             "aliases": ["Samsung", "三星"]},
            {"id": "sk-hynix", "type": "company",
             "aliases": ["SK Hynix", "SK海力士"]},
            {"id": "nvidia", "type": "company",
             "aliases": ["NVIDIA", "英伟达"]},
            {"id": "cxmt", "type": "company",
             "aliases": ["CXMT", "长鑫存储", "长鑫"]},
            {"id": "micron", "type": "company",
             "aliases": ["Micron", "美光"]},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def taxonomy(taxonomy_path):
    return Taxonomy(taxonomy_path)


@pytest.fixture
def repo_and_state():
    with tempfile.TemporaryDirectory() as d:
        repo = JsonlEventRepository(d, "storage")
        state = StateManager(d)
        yield repo, state, d


# ── Integration Test ──

class TestIntegration:
    """Full loop: agent output → bridge → store → query → context."""

    def test_full_loop(self, agent_event_threads, repo_and_state, taxonomy):
        repo, state, data_dir = repo_and_state
        threads = agent_event_threads["threads"]

        # ── Step 1: Bridge ingests agent output ──
        stats = ingest_batch(
            threads, "storage", "2026-05-28",
            repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )

        assert stats["ingested"] == 3
        assert stats["rejected"] == 0
        assert repo.count() == 3

        # ── Step 2: Query by topic ──
        events = repo.all()
        hbm_events = events_by_topic(events, "hbm")
        # 2 events tagged "hbm": thread #1 explicitly, thread #2 assessment mentions HBM→DRAM shift
        assert len(hbm_events) == 2

        nand_events = events_by_topic(events, "nand")
        assert len(nand_events) == 1
        assert "NAND" in nand_events[0].title

        # ── Step 3: Query by entity ──
        samsung_events = events_by_entity(events, "samsung")
        # 3 events mention Samsung: thread #1 explicitly, #2 & #3 in assessment text
        assert len(samsung_events) == 3

        cxmt_events = events_by_entity(events, "cxmt")
        assert len(cxmt_events) == 1

        # ── Step 4: Query by date ──
        result = query_events(events, date_from="2026-05-28", date_to="2026-05-28")
        assert len(result) == 3

        # ── Step 5: Query by scale ──
        daily_events = query_events(events, scale="daily")
        assert len(daily_events) == 3  # All ingested with daily scale_ref

        # ── Step 6: Generate context for next day ──
        ctx = generate_context(
            "storage", "daily", "2026-05-29",
            events, [], [],
        )

        # All 3 events should be carried forward (appeared in daily on 2026-05-28)
        assert len(ctx.carried_forward) == 3
        # Verify priority order (priority 1 first)
        assert ctx.carried_forward[0]["priority"] == 1

        # ── Step 7: Format context for agent prompt ──
        text = format_context_for_prompt(ctx)
        assert "Samsung" in text
        assert "Briefing Context" in text

    def test_two_day_loop(self, agent_event_threads, repo_and_state, taxonomy):
        """Simulate two days of briefings: day1 events carried to day2."""
        repo, state, data_dir = repo_and_state
        threads = agent_event_threads["threads"]

        # Day 1: ingest
        ingest_batch(threads, "storage", "2026-05-28", repo, state, taxonomy,
                    briefing_id="daily-2026-05-28")
        events_day1 = repo.all()

        # Day 2: generate context — should carry forward all 3
        ctx = generate_context("storage", "daily", "2026-05-29", events_day1, [], [])
        assert len(ctx.carried_forward) == 3

        # Day 2: mock agent produces only 1 new thread (the other 2 are cooling)
        # Mark 2 of the events as resolved
        for eid in events_day1[:2]:
            e = repo.get(eid.id)
            e.status = "cooling"
            repo.update(e)

        events_day2 = repo.all()
        ctx2 = generate_context("storage", "daily", "2026-05-30", events_day2, [], [])
        # Only active/emerging events carried forward
        carried_ids = {c["event_id"] for c in ctx2.carried_forward}
        # The cooling events should NOT be carried forward
        assert len(carried_ids) == 1  # Only the remaining active one

    def test_unassigned_detection(self, agent_event_threads, repo_and_state, taxonomy):
        """New events without scale_refs should show in unassigned_events."""
        repo, state, data_dir = repo_and_state
        threads = agent_event_threads["threads"]

        # Ingest WITHOUT briefing_id (no scale_refs)
        ingest_batch(threads, "storage", "2026-05-28", repo, state, taxonomy)

        events = repo.all()
        ctx = generate_context("storage", "daily", "2026-05-29", events, [], [])

        # All 3 should be unassigned
        assert len(ctx.unassigned_events) == 3
        # And no carried_forward (scale_refs are empty)
        assert len(ctx.carried_forward) == 0


# ── Causal & Judgment Ingestion ──

class TestCausalJudgmentIngestion:
    """Full loop: Agent output → bridge (events + causal + judgment) → store."""

    def test_ingest_causal_edges(self, agent_event_threads, repo_and_state, taxonomy):
        """After Bridge ingests threads, causal edges should be resolvable and storable."""
        repo, state, data_dir = repo_and_state

        # Step 1: Bridge ingests threads
        from story_bridge import ingest_batch
        ingest_batch(
            agent_event_threads["threads"], "storage", "2026-05-28",
            repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )

        # Step 2: Simulate _try_ingest_causal_and_judgments
        causal_repo = JsonlCausalRepository(data_dir)
        judgment_repo = JsonlJudgmentRepository(data_dir)
        from story_contracts import CausalEdge, Judgment
        from gate import gate_causal_edge, gate_judgment

        all_events = repo.all()
        event_ids = {e.id for e in all_events}

        for ce in agent_event_threads["causal_edges"]:
            cause_ev = repo.find_by_thread_id(ce["cause_thread_id"])
            effect_ev = repo.find_by_thread_id(ce["effect_thread_id"])
            assert cause_ev is not None, f"cause thread {ce['cause_thread_id']} not found"
            assert effect_ev is not None

            seq = state.next_causal_seq()
            edge = CausalEdge(
                id=f"causal-storage-{seq:04d}",
                cause_id=cause_ev.id,
                effect_id=effect_ev.id,
                mechanism=ce["mechanism"][:500],
                confidence=ce["confidence"],
                created="2026-05-28",
            )
            result = gate_causal_edge(edge, causal_repo.all(), event_ids)
            assert result.passed, f"Gate rejected: {result.errors}"
            causal_repo.add(edge)

        assert causal_repo.count() == 1
        stored = causal_repo.all()[0]
        assert stored.cause_id.startswith("event-")
        assert stored.effect_id.startswith("event-")

    def test_ingest_judgments(self, agent_event_threads, repo_and_state, taxonomy):
        """Entity and event_pair judgments should be storable."""
        repo, state, data_dir = repo_and_state

        from story_bridge import ingest_batch
        ingest_batch(
            agent_event_threads["threads"], "storage", "2026-05-28",
            repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )

        judgment_repo = JsonlJudgmentRepository(data_dir)
        from story_contracts import Judgment
        from gate import gate_judgment

        # Event pair judgment — resolve thread_ids to event_ids
        event_pair_jd = agent_event_threads["judgments"][1]
        event_ids_for_pair = []
        for tid in event_pair_jd["target_thread_ids"]:
            ev = repo.find_by_thread_id(tid)
            assert ev is not None, f"thread {tid} not found"
            event_ids_for_pair.append(ev.id)

        seq = state.next_judgment_seq()
        j = Judgment(
            id=f"judgment-storage-{seq:04d}",
            target_type="event_pair",
            target_ids=event_ids_for_pair,
            hypothesis=event_pair_jd["hypothesis"][:500],
            confidence=event_pair_jd["confidence"],
            made_at="2026-05-28",
            expected_verification=event_pair_jd["expected_verification"],
            triggered_by_events=event_ids_for_pair,
        )
        result = gate_judgment(j, judgment_repo.all())
        assert result.passed, f"Gate rejected: {result.errors}"
        judgment_repo.add(j)

        # Entity judgment
        entity_jd = agent_event_threads["judgments"][0]
        seq2 = state.next_judgment_seq()
        j2 = Judgment(
            id=f"judgment-storage-{seq2:04d}",
            target_type="entity",
            target_ids=entity_jd["target_entity_ids"],
            hypothesis=entity_jd["hypothesis"][:500],
            confidence=entity_jd["confidence"],
            made_at="2026-05-28",
            expected_verification=entity_jd["expected_verification"],
            triggered_by_events=[],
        )
        result2 = gate_judgment(j2, judgment_repo.all())
        assert result2.passed
        judgment_repo.add(j2)

        assert judgment_repo.count() == 2
        # Verify both types
        entities = judgment_repo.find_by_verdict("pending")
        assert len(entities) == 2

    def test_causal_to_judgment_link(self, agent_event_threads, repo_and_state, taxonomy):
        """Event pair judgment should be linked to its causal edge."""
        repo, state, data_dir = repo_and_state

        from story_bridge import ingest_batch
        ingest_batch(
            agent_event_threads["threads"], "storage", "2026-05-28",
            repo, state, taxonomy,
            briefing_id="daily-2026-05-28",
        )

        causal_repo = JsonlCausalRepository(data_dir)
        judgment_repo = JsonlJudgmentRepository(data_dir)
        from story_contracts import CausalEdge, Judgment
        from gate import gate_causal_edge, gate_judgment

        all_events = repo.all()
        event_ids = {e.id for e in all_events}

        # Ingest causal edge first
        ce = agent_event_threads["causal_edges"][0]
        cause_ev = repo.find_by_thread_id(ce["cause_thread_id"])
        effect_ev = repo.find_by_thread_id(ce["effect_thread_id"])
        seq = state.next_causal_seq()
        edge = CausalEdge(
            id=f"causal-storage-{seq:04d}",
            cause_id=cause_ev.id,
            effect_id=effect_ev.id,
            mechanism=ce["mechanism"][:500],
            confidence=ce["confidence"],
            created="2026-05-28",
        )
        causal_repo.add(edge)

        # Ingest event_pair judgment — should link to causal edge
        event_pair_jd = agent_event_threads["judgments"][1]
        event_ids_for_pair = []
        for tid in event_pair_jd["target_thread_ids"]:
            ev = repo.find_by_thread_id(tid)
            event_ids_for_pair.append(ev.id)

        # Find linked causal edge
        linked_causal = None
        for e in causal_repo.find_by_cause(event_ids_for_pair[0]):
            if e.effect_id in event_ids_for_pair:
                linked_causal = e.id
                break

        assert linked_causal is not None
        # Verify the link is correct — it should match our just-created edge
        assert linked_causal == edge.id
