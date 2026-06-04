"""Tests for cross-temporal event linkage subsystem."""
import pytest
from datetime import date

from stratum.contracts import (
    BriefingRef, CrossTemporalLink, CrossTemporalState, RegisterInput,
    RollupInput, TraceResult, scale_higher, scale_lower, SCALE_ORDER,
)
from stratum.subsystems.event_thread import (
    register_appearance, register_batch, rollup, trace_thread, trace_chain,
    get_threads_at_scale, get_unmerged_threads, get_thread_tree,
    resolve_thread, resolve_scale, generate_scale_summary, generate_full_summary,
)


# ── Fixtures ──

@pytest.fixture
def empty_state() -> CrossTemporalState:
    return CrossTemporalState(domain_id="storage")


@pytest.fixture
def daily_state() -> CrossTemporalState:
    """State with 3 daily threads, each appearing in daily briefings."""
    s = CrossTemporalState(domain_id="storage")
    register_batch(s, [
        RegisterInput("et-storage-0001", "daily-2026-05-25", "daily", "2026-05-25",
                      "Story 1", "lead", "Samsung ships HBM4 to NVIDIA"),
        RegisterInput("et-storage-0002", "daily-2026-05-26", "daily", "2026-05-26",
                      "Story 2", "supporting", "NAND prices stabilize"),
        RegisterInput("et-storage-0003", "daily-2026-05-27", "daily", "2026-05-27",
                      "Story 3", "lead", "Micron announces 32Gb DDR5"),
    ])
    return s


@pytest.fixture
def rolled_up_state(daily_state) -> CrossTemporalState:
    """State with daily threads rolled up to weekly."""
    s = daily_state
    rollup(s, RollupInput(
        source_thread_ids=["et-storage-0001", "et-storage-0002", "et-storage-0003"],
        target_thread_id="et-storage-0010",
        target_scale="weekly",
        briefing_id="weekly-2026-W22",
        date="2026-05-31",
        synthesis="Memory market heats up: HBM4 shipping, NAND stabilizing, DDR5 expanding",
    ))
    return s


# ── Scale Utilities ──

class TestScaleUtils:
    def test_scale_higher_daily(self):
        assert scale_higher("daily") == "weekly"

    def test_scale_higher_weekly(self):
        assert scale_higher("weekly") == "monthly"

    def test_scale_higher_monthly(self):
        assert scale_higher("monthly") == "quarterly"

    def test_scale_higher_quarterly(self):
        assert scale_higher("quarterly") == "yearly"

    def test_scale_higher_top(self):
        assert scale_higher("yearly") is None

    def test_scale_lower_weekly(self):
        assert scale_lower("weekly") == "daily"

    def test_scale_lower_bottom(self):
        assert scale_lower("daily") is None

    def test_scale_order(self):
        assert SCALE_ORDER["daily"] == 0
        assert SCALE_ORDER["yearly"] == 4


# ── BriefingRef ──

class TestBriefingRef:
    def test_valid_ref(self):
        ref = BriefingRef("daily-2026-05-28", "daily", "2026-05-28",
                          "Story 1", "lead", "HBM4 update")
        assert ref.scale == "daily"
        assert ref.prominence == "lead"

    def test_invalid_scale_raises(self):
        with pytest.raises(ValueError):
            BriefingRef("x", "hourly", "2026-05-28", "S1", "lead", "synthesis")


# ── CrossTemporalLink ──

class TestCrossTemporalLink:
    def test_add_appearance_sorts_chronologically(self):
        link = CrossTemporalLink("et-1", created_scale="daily")
        link.add_appearance(BriefingRef("daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "a"))
        link.add_appearance(BriefingRef("daily-2026-05-26", "daily", "2026-05-26", "S1", "lead", "b"))
        assert link.appearances[0].date == "2026-05-26"

    def test_add_appearance_replaces_same_briefing(self):
        link = CrossTemporalLink("et-1", created_scale="daily")
        link.add_appearance(BriefingRef("daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "old"))
        link.add_appearance(BriefingRef("daily-2026-05-28", "daily", "2026-05-28", "S1", "supporting", "new"))

        assert len(link.appearances) == 1
        assert link.appearances[0].prominence == "supporting"
        assert link.appearances[0].synthesis == "new"

    def test_get_appearances_at_scale(self):
        link = CrossTemporalLink("et-1", created_scale="daily")
        link.add_appearance(BriefingRef("daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "a"))
        link.add_appearance(BriefingRef("weekly-2026-W22", "weekly", "2026-05-31", "S1", "supporting", "b"))
        dailies = link.get_appearances_at_scale("daily")
        assert len(dailies) == 1
        assert dailies[0].briefing_id == "daily-2026-05-28"

    def test_has_appeared_at_scale(self):
        link = CrossTemporalLink("et-1", created_scale="daily")
        link.add_appearance(BriefingRef("daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "a"))
        assert link.has_appeared_at_scale("daily") is True
        assert link.has_appeared_at_scale("weekly") is False


# ── CrossTemporalState ──

class TestCrossTemporalState:
    def test_get_link_missing(self):
        s = CrossTemporalState("test")
        assert s.get_link("nonexistent") is None

    def test_get_or_create_creates(self):
        s = CrossTemporalState("test")
        link = s.get_or_create_link("et-1", "daily")
        assert link.thread_id == "et-1"
        assert link.created_scale == "daily"
        assert "et-1" in s.links

    def test_get_or_create_returns_existing(self):
        s = CrossTemporalState("test")
        link1 = s.get_or_create_link("et-1", "daily")
        link2 = s.get_or_create_link("et-1", "monthly")  # should not overwrite
        assert link1 is link2
        assert link2.created_scale == "daily"


# ── Register Appearance ──

class TestRegister:
    def test_register_single(self, empty_state):
        inp = RegisterInput("et-1", "daily-2026-05-28", "daily", "2026-05-28",
                           "Story 1", "lead", "HBM4 update")
        link = register_appearance(empty_state, inp)
        assert len(link.appearances) == 1
        assert link.appearances[0].briefing_id == "daily-2026-05-28"

    def test_register_same_thread_multiple_days(self, empty_state):
        register_appearance(empty_state, RegisterInput(
            "et-1", "daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "day1"))
        register_appearance(empty_state, RegisterInput(
            "et-1", "daily-2026-05-29", "daily", "2026-05-29", "S1", "supporting", "day2"))
        link = empty_state.links["et-1"]
        assert len(link.appearances) == 2

    def test_register_same_briefing_is_idempotent(self, empty_state):
        register_appearance(empty_state, RegisterInput(
            "et-1", "daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "day1"))
        register_appearance(empty_state, RegisterInput(
            "et-1", "daily-2026-05-28", "daily", "2026-05-28", "S1", "supporting", "updated"))

        link = empty_state.links["et-1"]
        assert len(link.appearances) == 1
        assert link.appearances[0].prominence == "supporting"
        assert link.appearances[0].synthesis == "updated"

    def test_register_batch(self, empty_state):
        inputs = [
            RegisterInput("et-1", "daily-2026-05-28", "daily", "2026-05-28", "S1", "lead", "a"),
            RegisterInput("et-2", "daily-2026-05-28", "daily", "2026-05-28", "S2", "supporting", "b"),
        ]
        links = register_batch(empty_state, inputs)
        assert len(links) == 2
        assert len(empty_state.links) == 2


# ── Rollup ──

class TestRollup:
    def test_rollup_links_sources(self, daily_state):
        s = daily_state
        result = rollup(s, RollupInput(
            source_thread_ids=["et-storage-0001", "et-storage-0002"],
            target_thread_id="et-storage-0010",
            target_scale="weekly",
            briefing_id="weekly-2026-W22",
            date="2026-05-31",
            synthesis="Memory update",
        ))
        assert result["stats"]["rolled_up"] == 2
        assert s.links["et-storage-0001"].merged_into == "et-storage-0010"
        assert s.links["et-storage-0002"].merged_into == "et-storage-0010"
        assert set(s.links["et-storage-0010"].child_threads) == {
            "et-storage-0001", "et-storage-0002"}

    def test_rollup_already_merged(self, daily_state):
        s = daily_state
        # First rollup
        rollup(s, RollupInput(
            ["et-storage-0001"], "et-0010", "weekly",
            "weekly-2026-W22", "2026-05-31", "synthesis"))
        # Second rollup with same source
        result = rollup(s, RollupInput(
            ["et-storage-0001"], "et-0011", "weekly",
            "weekly-2026-W22", "2026-05-31", "synthesis2"))
        assert result["stats"]["already_merged"] == 1
        assert result["stats"]["rolled_up"] == 0

    def test_rollup_not_found(self, empty_state):
        result = rollup(empty_state, RollupInput(
            ["et-nonexistent"], "et-0010", "weekly",
            "weekly-2026-W22", "2026-05-31", "synthesis"))
        assert result["stats"]["not_found"] == 1

    def test_rollup_registers_target_appearance(self, daily_state):
        s = daily_state
        rollup(s, RollupInput(
            ["et-storage-0001"], "et-0010", "weekly",
            "weekly-2026-W22", "2026-05-31", "Weekly synthesis"))
        target = s.links["et-0010"]
        assert target.has_appeared_at_scale("weekly")
        assert target.appearances[0].synthesis == "Weekly synthesis"

    def test_rollup_target_appearance_is_idempotent_on_rerun(self, daily_state):
        s = daily_state
        first = RollupInput(
            ["et-storage-0001"], "et-0010", "weekly",
            "weekly-2026-W22", "2026-05-31", "Weekly synthesis")
        second = RollupInput(
            ["et-storage-0001"], "et-0010", "weekly",
            "weekly-2026-W22", "2026-05-31", "Updated weekly synthesis")

        rollup(s, first)
        rollup(s, second)

        target = s.links["et-0010"]
        assert len(target.appearances) == 1
        assert target.appearances[0].synthesis == "Updated weekly synthesis"

    def test_rollup_preserves_source_scale(self, rolled_up_state):
        s = rolled_up_state
        # Sources still know their original scale
        assert s.links["et-storage-0001"].created_scale == "daily"
        assert s.links["et-storage-0010"].created_scale == "weekly"


# ── Trace ──

class TestTrace:
    def test_trace_basic(self, daily_state):
        result = trace_thread(daily_state, "et-storage-0001")
        assert result is not None
        assert result.thread_id == "et-storage-0001"
        assert len(result.chain) == 1
        assert result.chain[0].scale == "daily"

    def test_trace_rolled_up(self, rolled_up_state):
        s = rolled_up_state
        result = trace_thread(s, "et-storage-0001")
        assert result is not None
        # Chain should have: daily appearance + weekly rollup appearance
        scales_in_chain = {r.scale for r in result.chain}
        assert "daily" in scales_in_chain
        assert "weekly" in scales_in_chain
        assert result.merged_into_higher == "et-storage-0010"

    def test_trace_missing_thread(self, empty_state):
        assert trace_thread(empty_state, "nonexistent") is None

    def test_trace_missing_scales(self, daily_state):
        """Daily thread without rollup should show missing scales."""
        result = trace_thread(daily_state, "et-storage-0001")
        assert not result.is_complete
        assert "weekly" in result.missing_scales
        assert "monthly" in result.missing_scales

    def test_trace_complete_chain(self, rolled_up_state):
        """After rollup to weekly, daily source still has missing scales above."""
        s = rolled_up_state
        result = trace_thread(s, "et-storage-0001")
        # Daily → weekly is covered, but monthly/quarterly/yearly are missing
        assert "monthly" in result.missing_scales
        assert "quarterly" in result.missing_scales
        assert "yearly" in result.missing_scales

    def test_trace_chain_ids(self, rolled_up_state):
        s = rolled_up_state
        chain = trace_chain(s, "et-storage-0001")
        assert chain == ["et-storage-0001", "et-storage-0010"]

    def test_trace_chain_no_parent(self, daily_state):
        chain = trace_chain(daily_state, "et-storage-0001")
        assert chain == ["et-storage-0001"]


# ── Multi-Scale Rollup (Full Vertical Chain) ──

class TestFullVerticalChain:
    def test_daily_to_yearly(self, daily_state):
        """Test the full chain: daily → weekly → monthly → quarterly → yearly."""
        s = daily_state

        # Weekly rollup
        rollup(s, RollupInput(
            ["et-storage-0001"], "et-w1", "weekly",
            "weekly-2026-W22", "2026-05-31", "Weekly synthesis"))
        # Monthly rollup
        rollup(s, RollupInput(
            ["et-w1"], "et-m1", "monthly",
            "monthly-2026-05", "2026-06-01", "Monthly synthesis"))
        # Quarterly rollup
        rollup(s, RollupInput(
            ["et-m1"], "et-q1", "quarterly",
            "quarterly-2026-Q2", "2026-07-01", "Quarterly synthesis"))
        # Yearly rollup
        rollup(s, RollupInput(
            ["et-q1"], "et-y1", "yearly",
            "yearly-2026", "2027-01-01", "Yearly synthesis"))

        # Trace from daily thread
        chain = trace_chain(s, "et-storage-0001")
        assert chain == ["et-storage-0001", "et-w1", "et-m1", "et-q1", "et-y1"]

        result = trace_thread(s, "et-storage-0001")
        scales = {r.scale for r in result.chain}
        assert scales == {"daily", "weekly", "monthly", "quarterly", "yearly"}

        # Check child thread counts at each level
        assert len(s.links["et-w1"].child_threads) == 1
        assert len(s.links["et-m1"].child_threads) == 1
        assert len(s.links["et-q1"].child_threads) == 1
        assert len(s.links["et-y1"].child_threads) == 1


# ── Query ──

class TestQuery:
    def test_get_threads_at_scale(self, rolled_up_state):
        s = rolled_up_state
        dailies = get_threads_at_scale(s, "daily")
        assert len(dailies) == 3  # only the source threads

        weeklies = get_threads_at_scale(s, "weekly")
        assert len(weeklies) == 1  # the rollup target

    def test_get_threads_at_scale_excludes_resolved(self, daily_state):
        s = daily_state
        resolve_thread(s, "et-storage-0001")
        active = get_threads_at_scale(s, "daily", only_active=True)
        assert len(active) == 2
        assert all(l.thread_id != "et-storage-0001" for l in active)

    def test_get_unmerged_threads(self, rolled_up_state):
        s = rolled_up_state
        unmerged = get_unmerged_threads(s, "daily")
        # All 3 daily threads were rolled up
        assert len(unmerged) == 0

        # But et-storage-0003 was not rolled up? Wait, yes it was in the fixture
        # Add a new unmerged thread
        register_appearance(s, RegisterInput(
            "et-storage-0004", "daily-2026-05-30", "daily", "2026-05-30",
            "Story 4", "lead", "New unmerged story"))
        unmerged = get_unmerged_threads(s, "daily")
        assert len(unmerged) == 1
        assert unmerged[0].thread_id == "et-storage-0004"

    def test_get_thread_tree(self, rolled_up_state):
        s = rolled_up_state
        tree = get_thread_tree(s, "et-storage-0010")
        assert tree["thread"].thread_id == "et-storage-0010"
        assert len(tree["children"]) == 3
        child_ids = {c.thread_id for c in tree["children"]}
        assert child_ids == {"et-storage-0001", "et-storage-0002", "et-storage-0003"}

    def test_get_thread_tree_leaf(self, rolled_up_state):
        s = rolled_up_state
        tree = get_thread_tree(s, "et-storage-0001")
        assert tree["thread"].thread_id == "et-storage-0001"
        assert tree["parent"].thread_id == "et-storage-0010"
        assert tree["children"] == []


# ── Resolution ──

class TestResolution:
    def test_resolve_thread(self, daily_state):
        s = daily_state
        link = resolve_thread(s, "et-storage-0001", "2026-05-30")
        assert link is not None
        assert link.is_resolved is True
        assert link.resolved_at == "2026-05-30"

    def test_resolve_nonexistent(self, empty_state):
        assert resolve_thread(empty_state, "nonexistent") is None

    def test_resolve_scale(self, daily_state):
        s = daily_state
        count = resolve_scale(s, "daily")
        assert count == 3
        for link in s.links.values():
            assert link.is_resolved is True

    def test_resolve_scale_only_matching(self, rolled_up_state):
        s = rolled_up_state
        # Only daily threads get resolved
        count = resolve_scale(s, "daily")
        assert count == 3
        # Weekly target should NOT be resolved
        assert s.links["et-storage-0010"].is_resolved is False


# ── Summary Generation ──

class TestSummary:
    def test_scale_summary(self, daily_state):
        s = daily_state
        summary = generate_scale_summary(s, "daily")
        assert summary["scale"] == "daily"
        assert summary["total_threads"] == 3
        assert summary["active_threads"] == 3
        assert summary["resolved_threads"] == 0

    def test_scale_summary_after_resolution(self, daily_state):
        s = daily_state
        resolve_scale(s, "daily")
        summary = generate_scale_summary(s, "daily")
        assert summary["active_threads"] == 0
        assert summary["resolved_threads"] == 3

    def test_full_summary(self, rolled_up_state):
        s = rolled_up_state
        summary = generate_full_summary(s)
        assert summary["domain"] == "storage"
        assert summary["total_threads"] == 4  # 3 daily + 1 weekly
        assert summary["scales"]["daily"]["total_threads"] == 3
        assert summary["scales"]["weekly"]["total_threads"] == 1
        # Weekly has 3 children absorbed
        assert summary["scales"]["weekly"]["total_children_absorbed"] == 3

    def test_empty_summary(self, empty_state):
        summary = generate_full_summary(empty_state)
        assert summary["total_threads"] == 0


# ── Integration: End-to-End Daily-to-Weekly Flow ──

class TestEndToEnd:
    def test_daily_to_weekly_flow(self):
        """Simulate a real workflow: daily briefings → weekly rollup."""
        s = CrossTemporalState(domain_id="storage")

        # Day 1: three threads appear in daily briefing
        register_batch(s, [
            RegisterInput("et-0001", "daily-2026-05-28", "daily", "2026-05-28",
                         "HBM4 Race", "lead", "Samsung ships HBM4 samples"),
            RegisterInput("et-0002", "daily-2026-05-28", "daily", "2026-05-28",
                         "NAND Pricing", "supporting", "QLC NAND prices drop 5%"),
            RegisterInput("et-0003", "daily-2026-05-28", "daily", "2026-05-28",
                         "DDR5 Migration", "supporting", "Server DDR5 adoption at 40%"),
        ])

        # Day 2: et-0001 continues, new thread appears
        register_appearance(s, RegisterInput(
            "et-0001", "daily-2026-05-29", "daily", "2026-05-29",
            "HBM4 Race", "lead", "NVIDIA confirms HBM4 qualification"))
        register_appearance(s, RegisterInput(
            "et-0004", "daily-2026-05-29", "daily", "2026-05-29",
            "Fab Expansion", "lead", "TSMC starts 2nm risk production"))

        # End of week: roll up to weekly
        rollup(s, RollupInput(
            ["et-0001", "et-0002", "et-0003"],
            "et-w01", "weekly",
            "weekly-2026-W22", "2026-05-31",
            "Memory market: HBM4 race intensifies, NAND/QLC pricing pressure, DDR5 migration accelerates",
        ))

        # Verify
        # et-0001 appeared twice in daily, once in weekly
        et1 = s.links["et-0001"]
        assert et1.has_appeared_at_scale("daily")
        assert et1.merged_into == "et-w01"

        # et-0004 did NOT get rolled up (not in source list)
        et4 = s.links["et-0004"]
        assert et4.merged_into is None

        # Trace et-0001
        result = trace_thread(s, "et-0001")
        assert len(result.chain) == 3  # 2 daily + 1 weekly
        assert not result.is_complete  # Still missing monthly+

        # et-0004 trace shows only daily
        result4 = trace_thread(s, "et-0004")
        assert len(result4.chain) == 1

        # Unmerged threads at daily scale
        unmerged = get_unmerged_threads(s, "daily")
        assert len(unmerged) == 1
        assert unmerged[0].thread_id == "et-0004"
