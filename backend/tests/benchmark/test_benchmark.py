"""
Part 3: Competitor comparison benchmark.
Documented comparison — no live API calls to competitors.

LDVELH scores are placeholder defaults, meant to be replaced by empirical
results from Part 1 (memory tests) and Part 2 (compliance tests).
Competitor scores are documented estimates from public knowledge.
"""

from __future__ import annotations

import pytest

from .report_builder import ReportBuilder

pytestmark = pytest.mark.benchmark

# =============================================================================
# COMPARISON AXES
# =============================================================================

AXES = [
    "Memory Persistence",
    "Entity Tracking",
    "Mechanical Enforcement",
    "Narrative Coherence",
]

# =============================================================================
# COMPETITOR DATA (documented assessments from public knowledge)
#
# Each score is 0-10 based on the competitor's publicly known architecture:
# - 0: Feature doesn't exist
# - 1-3: Basic/minimal implementation
# - 4-6: Moderate implementation
# - 7-9: Strong implementation
# - 10: State-of-the-art
# =============================================================================

COMPETITORS = {
    "AI Dungeon": {
        "Memory Persistence": 2,
        "Entity Tracking": 1,
        "Mechanical Enforcement": 0,
        "Narrative Coherence": 3,
        "justification": {
            "Memory Persistence": "World info pins + /remember, but no structured DB. Context window ~8K tokens.",
            "Entity Tracking": "No entity registry. Names drift across sessions.",
            "Mechanical Enforcement": "No dice or mechanical system.",
            "Narrative Coherence": "GPT-based, some tone consistency. No fact enforcement.",
        },
    },
    "NovelAI": {
        "Memory Persistence": 5,
        "Entity Tracking": 3,
        "Mechanical Enforcement": 0,
        "Narrative Coherence": 4,
        "justification": {
            "Memory Persistence": "Lorebook with keyword triggers. Injected into context on mention.",
            "Entity Tracking": "Lorebook entries per entity, but no relational tracking or dedup.",
            "Mechanical Enforcement": "No dice. No rule system.",
            "Narrative Coherence": "Fine-tuned models for tone. No structured fact checking.",
        },
    },
    "FableAI": {
        "Memory Persistence": 4,
        "Entity Tracking": 4,
        "Mechanical Enforcement": 0,
        "Narrative Coherence": 5,
        "justification": {
            "Memory Persistence": "Session memory with entity summaries. Resets between sessions.",
            "Entity Tracking": "Character cards, basic relationship tracking.",
            "Mechanical Enforcement": "No dice. Story is AI-directed.",
            "Narrative Coherence": "Scene structure helps continuity. No immutable facts.",
        },
    },
    "Fables.gg": {
        "Memory Persistence": 3,
        "Entity Tracking": 3,
        "Mechanical Enforcement": 0,
        "Narrative Coherence": 4,
        "justification": {
            "Memory Persistence": "Scene-based, visual focus. Character cards persist.",
            "Entity Tracking": "Character/location cards. No cross-reference tracking.",
            "Mechanical Enforcement": "No dice or rule system.",
            "Narrative Coherence": "Scene structure. Limited cross-scene memory.",
        },
    },
}

# LDVELH empirical placeholder scores — updated by run_benchmark.py with real results
# These defaults reflect architectural capability, not measured performance
LDVELH_DEFAULTS = {
    "Memory Persistence": 8,
    "Entity Tracking": 8,
    "Mechanical Enforcement": 9,
    "Narrative Coherence": 7,
}


def compute_ldvelh_scores(
    memory_results: dict | None = None,
    compliance_results: dict | None = None,
) -> dict[str, int]:
    """Compute LDVELH scores from empirical test results.

    Converts Part 1 + Part 2 pass rates into 0-10 scores.
    Falls back to LDVELH_DEFAULTS if no results available.
    """
    scores = dict(LDVELH_DEFAULTS)

    if memory_results:
        total = memory_results.get("passed", 0) + memory_results.get("failed", 0)
        if total > 0:
            rate = memory_results["passed"] / total
            # Memory Persistence: entity persistence + relation tests
            scores["Memory Persistence"] = round(rate * 10)
            # Entity Tracking: dedup stress tests
            scores["Entity Tracking"] = round(rate * 10)

    if compliance_results:
        total = compliance_results.get("passed", 0) + compliance_results.get("failed", 0)
        if total > 0:
            rate = compliance_results["passed"] / total
            # Mechanical Enforcement: compliance tests A + B
            scores["Mechanical Enforcement"] = round(rate * 10)
            # Narrative Coherence: compliance tests C + D
            scores["Narrative Coherence"] = round(rate * 10)

    return scores


def build_comparison_table(ldvelh_scores: dict[str, int] | None = None) -> str:
    """Build the comparison table as markdown."""
    if ldvelh_scores is None:
        ldvelh_scores = LDVELH_DEFAULTS

    report = ReportBuilder()
    all_data = {"LDVELH": ldvelh_scores, **{name: {a: data[a] for a in AXES} for name, data in COMPETITORS.items()}}

    headers = ["Feature"] + list(all_data.keys())
    rows = []
    for axis in AXES:
        row = [axis] + [str(all_data[name].get(axis, "?")) for name in all_data]
        rows.append(row)

    totals = ["**Total**"]
    for name in all_data:
        total = sum(all_data[name].get(axis, 0) for axis in AXES)
        totals.append(f"**{total}**")
    rows.append(totals)

    return report.add_table(headers, rows)


# =============================================================================
# TESTS
# =============================================================================


class TestCompetitorBenchmark:
    """Generate and validate competitor comparison data."""

    def test_competitor_data_complete(self):
        """All competitors have scores and justifications for all axes."""
        for name, data in COMPETITORS.items():
            for axis in AXES:
                assert axis in data, f"Missing axis '{axis}' for {name}"
                assert 0 <= data[axis] <= 10, f"Invalid score for {name}/{axis}: {data[axis]}"
            assert "justification" in data, f"Missing justification for {name}"
            for axis in AXES:
                assert axis in data["justification"], (
                    f"Missing justification for {name}/{axis}"
                )

    def test_competitors_lack_mechanical(self):
        """All competitors score 0 on Mechanical Enforcement (unique to LDVELH)."""
        for name, data in COMPETITORS.items():
            assert data["Mechanical Enforcement"] == 0, (
                f"{name} has non-zero Mechanical Enforcement: {data['Mechanical Enforcement']}"
            )

    def test_default_scores_valid(self):
        """LDVELH default scores are within range."""
        for axis in AXES:
            assert axis in LDVELH_DEFAULTS
            assert 0 <= LDVELH_DEFAULTS[axis] <= 10

    def test_ldvelh_leads_overall_with_defaults(self):
        """With default scores, LDVELH leads all competitors."""
        ldvelh_total = sum(LDVELH_DEFAULTS.values())
        for name, data in COMPETITORS.items():
            comp_total = sum(data[axis] for axis in AXES)
            assert ldvelh_total > comp_total, (
                f"LDVELH ({ldvelh_total}) does not lead {name} ({comp_total})"
            )

    def test_generate_comparison_matrix(self):
        """Comparison matrix generates valid markdown."""
        table = build_comparison_table()
        assert "LDVELH" in table
        assert "AI Dungeon" in table
        assert "NovelAI" in table
        assert len(table) > 100

    def test_generate_with_empirical_scores(self):
        """Matrix works with empirical scores from test results."""
        empirical = compute_ldvelh_scores(
            memory_results={"passed": 18, "failed": 2},
            compliance_results={"passed": 8, "failed": 2},
        )
        table = build_comparison_table(empirical)
        assert "LDVELH" in table
        # Empirical scores should be reflected
        assert str(empirical["Memory Persistence"]) in table

    def test_justification_report(self, tmp_path):
        """Generate a justification report for all scores."""
        report = ReportBuilder("Score Justifications")

        for name, data in COMPETITORS.items():
            lines = []
            for axis in AXES:
                lines.append(f"- **{axis}** ({data[axis]}/10): {data['justification'][axis]}")
            report.add_section(name, "\n".join(lines))

        markdown = report.build()
        output = tmp_path / "justifications.md"
        output.write_text(markdown)
        assert output.exists()
        assert "Lorebook" in output.read_text()  # NovelAI justification
