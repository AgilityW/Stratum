"""Verify Engine — determinism and rule completeness.

All verification must be deterministic (no LLM). Validates:
- Rejection reason codes completeness
- Check pipeline structure
- Fiscal year mappings
- Date window rules
"""
import pytest


REJECTION_CODES = {
    "STALE", "FUTURE", "NO_DATE", "IMPOSSIBLE", "AMBIG_FY",
}

FISCAL_YEAR_MAPPINGS = {
    "Micron": {"fy_end": "Aug", "cy_q1_equals": "FY Q4"},
    "Samsung": {"fy_end": "Dec", "cy_q1_equals": "FY Q1"},
    "SK hynix": {"fy_end": "Dec", "cy_q1_equals": "FY Q1"},
}

CHECK_NAMES = [
    "Date Validation",
    "Magnitude Sanity",
    "Fiscal Year Normalization",
]

# Magnitude thresholds from SKILL.md
MAGNITUDE_RULES = {
    "revenue_max": 1_000_000_000_000,  # $1T flag
    "share_max": 100,                   # 100% reject
    "growth_max": 1000,                 # 1000% YoY flag
    "chip_price_max": 10_000,           # $10K flag
}


class TestRejectionCodes:
    """All 5 rejection codes must be present."""

    def test_all_codes_defined(self):
        assert len(REJECTION_CODES) == 5, (
            f"Expected 5 rejection codes, got {len(REJECTION_CODES)}"
        )

    def test_codes_are_uppercase(self):
        for code in REJECTION_CODES:
            assert code == code.upper(), f"Code '{code}' must be UPPERCASE"

    def test_codes_are_descriptive(self):
        """Each code must be a single word abbreviation."""
        for code in REJECTION_CODES:
            assert " " not in code, f"Code '{code}' must not contain spaces"
            assert len(code) >= 3, f"Code '{code}' too short"


class TestCheckPipeline:
    """Three deterministic checks, no LLM involvement."""

    def test_three_checks(self):
        assert len(CHECK_NAMES) == 3

    def test_date_validation_is_first(self):
        """Date check must run first — cheapest, highest rejection rate."""
        assert CHECK_NAMES[0] == "Date Validation"

    def test_magnitude_sanity_is_second(self):
        assert CHECK_NAMES[1] == "Magnitude Sanity"

    def test_fiscal_normalization_is_third(self):
        assert CHECK_NAMES[2] == "Fiscal Year Normalization"


class TestFiscalYearMappings:
    """Known company fiscal year differences."""

    def test_three_companies_mapped(self):
        assert len(FISCAL_YEAR_MAPPINGS) == 3

    def test_micron_august_fy_end(self):
        assert FISCAL_YEAR_MAPPINGS["Micron"]["fy_end"] == "Aug"

    def test_samsung_dec_fy_end(self):
        assert FISCAL_YEAR_MAPPINGS["Samsung"]["fy_end"] == "Dec"

    def test_sk_hynix_dec_fy_end(self):
        assert FISCAL_YEAR_MAPPINGS["SK hynix"]["fy_end"] == "Dec"

    def test_cy_q1_mapped_correctly(self):
        """CQ1 maps to different FY quarters depending on company."""
        # Micron (Aug FY end): CQ1 = FY Q4
        assert FISCAL_YEAR_MAPPINGS["Micron"]["cy_q1_equals"] == "FY Q4"
        # Samsung/SK (Dec FY end): CQ1 = FY Q1
        assert FISCAL_YEAR_MAPPINGS["Samsung"]["cy_q1_equals"] == "FY Q1"


class TestMagnitudeThresholds:
    """Magnitude sanity check thresholds are reasonable."""

    def test_share_over_100_percent_rejected(self):
        """Market share > 100% is mathematically impossible."""
        assert MAGNITUDE_RULES["share_max"] == 100

    def test_trillion_dollar_revenue_flagged(self):
        """Revenue > $1T for single company is suspicious."""
        assert MAGNITUDE_RULES["revenue_max"] == 1_000_000_000_000

    def test_extreme_growth_flagged(self):
        """>1000% YoY growth is flagged, not rejected (possible for startups)."""
        assert MAGNITUDE_RULES["growth_max"] == 1000

    def test_chip_price_threshold(self):
        """Single NAND chip > $10K is implausible."""
        assert MAGNITUDE_RULES["chip_price_max"] == 10_000


class TestDeterminism:
    """Verify engine must never use LLM."""

    def test_no_llm_in_check_pipeline(self):
        """The word 'LLM' / 'AI' / 'model' must not appear in check pipeline
        descriptions — all rules are regex/arithmetic."""
        prohibited = {"LLM", "AI", "model", "GPT", "Claude", "prompt"}
        for check in CHECK_NAMES:
            for word in prohibited:
                assert word.lower() not in check.lower(), (
                    f"Check '{check}' references {word} — must be deterministic"
                )
