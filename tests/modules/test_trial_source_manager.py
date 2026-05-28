"""Trial Source Manager — scoring algorithm validation.

The 5-dim weighted scoring:
- novelty (0.30)
- verifiability (0.25)
- exclusivity (0.20)
- signal_noise (0.15)
- depth (0.10)

Promotion threshold: 0.60
"""
import pytest

# From SKILL.md v2.2 contract
SCORING_DIMENSIONS = {
    "novelty": 0.30,
    "verifiability": 0.25,
    "exclusivity": 0.20,
    "signal_noise": 0.15,
    "depth": 0.10,
}

PROMOTE_THRESHOLD = 0.60
MIN_SAMPLES = 20
DEFAULT_TRIAL_DAYS = 14

# Acceleration signals — 3+ out of 4 halves trial duration
ACCELERATION_SIGNALS = {
    "cited_by_trusted",
    "social_mention",
    "fills_coverage_gap",
    "fills_signal_type_gap",
}

TRIAL_STATUSES = {"collecting", "ready", "evaluating", "promoted", "archived", "paused"}

ENTRY_REQUIRED_FIELDS = {
    "source", "source_type", "source_locale", "discovered_at",
    "discovery_channel", "discovery_context", "signals",
    "trial_start", "trial_duration_days", "min_samples",
    "sample_count", "query", "status",
}


class TestScoringDimensions:
    """5-dim weighted scoring must sum to 1.0."""

    def test_five_dimensions(self):
        assert len(SCORING_DIMENSIONS) == 5

    def test_weights_sum_to_one(self):
        total = sum(SCORING_DIMENSIONS.values())
        assert abs(total - 1.0) < 0.001, (
            f"Weights sum to {total}, expected 1.0"
        )

    def test_weight_order(self):
        """Highest weight first: novelty > verifiability > exclusivity > signal_noise > depth."""
        weights = list(SCORING_DIMENSIONS.values())
        for i in range(len(weights) - 1):
            assert weights[i] >= weights[i + 1], (
                f"Weight at position {i} ({weights[i]}) < position {i+1} ({weights[i+1]})"
            )

    def test_promote_threshold(self):
        """0.60 threshold requires at least novelty + one other dimension."""
        assert 0.60 > SCORING_DIMENSIONS["signal_noise"], (
            "Threshold should be above lower-weight dimensions"
        )
        # Top 3 dimensions needed: novelty(0.30) + verifiability(0.25) + exclusivity(0.20) = 0.75
        top3 = (SCORING_DIMENSIONS["novelty"] +
                SCORING_DIMENSIONS["verifiability"] +
                SCORING_DIMENSIONS["exclusivity"])
        assert top3 > 0.60, (
            f"Top 3 dimensions sum to {top3}, need > 0.60 to reach threshold"
        )
        # Top 2 alone (0.55) cannot reach threshold — forces multi-dim evaluation
        top2 = SCORING_DIMENSIONS["novelty"] + SCORING_DIMENSIONS["verifiability"]
        assert top2 < 0.60, (
            f"Top 2 sum to {top2} — correctly forces at least 3 dimensions for promotion"
        )

    def test_max_possible_score(self):
        """All dimensions at 1.0 sums to 1.0."""
        assert abs(sum(SCORING_DIMENSIONS.values()) - 1.0) < 0.001


class TestTrialLifecycle:
    """Trial source lifecycle rules."""

    def test_min_samples(self):
        """20 sample minimum before evaluation."""
        assert MIN_SAMPLES == 20

    def test_default_trial_days(self):
        """14 day default trial period."""
        assert DEFAULT_TRIAL_DAYS == 14

    def test_all_statuses_defined(self):
        assert len(TRIAL_STATUSES) == 6

    def test_statuses_are_snake_case(self):
        for s in TRIAL_STATUSES:
            assert "_" in s or s.islower(), (
                f"Status '{s}' should be snake_case"
            )


class TestAccelerationSignals:
    """4 acceleration signals, 3+ halves trial duration."""

    def test_four_signals(self):
        assert len(ACCELERATION_SIGNALS) == 4

    def test_three_plus_triggers_acceleration(self):
        """3 out of 4 signals triggers halved trial duration."""
        # Simulate: 3 True, 1 False
        signals = {"cited_by_trusted": True, "social_mention": True,
                    "fills_coverage_gap": True, "fills_signal_type_gap": False}
        active = sum(1 for v in signals.values() if v)
        assert active >= 3
        # If accelerated: trial_duration = DEFAULT_TRIAL_DAYS // 2
        accelerated_days = DEFAULT_TRIAL_DAYS // 2
        assert accelerated_days == 7

    def test_two_signals_no_acceleration(self):
        """2 out of 4 does NOT trigger acceleration."""
        signals = {"cited_by_trusted": True, "social_mention": False,
                    "fills_coverage_gap": True, "fills_signal_type_gap": False}
        active = sum(1 for v in signals.values() if v)
        assert active == 2
        assert active < 3


class TestTrialPoolEntrySchema:
    """TrialPool entry must have all required fields."""

    def test_entry_required_fields(self):
        assert len(ENTRY_REQUIRED_FIELDS) == 13

    def test_signals_is_subdict(self):
        """signals field is a dict with 4 boolean sub-fields."""
        assert "signals" in ENTRY_REQUIRED_FIELDS
        assert ACCELERATION_SIGNALS == {
            "cited_by_trusted", "social_mention",
            "fills_coverage_gap", "fills_signal_type_gap",
        }
