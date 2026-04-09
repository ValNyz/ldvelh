"""
Markdown report builder for benchmark results.
"""

from __future__ import annotations

from datetime import datetime


class ReportBuilder:
    """Builds a Markdown report from benchmark results."""

    def __init__(self, title: str = "LDVELH Benchmark Report"):
        self.title = title
        self._sections: list[tuple[str, str]] = []

    def add_section(self, heading: str, content: str) -> None:
        """Add a section with a heading and markdown content."""
        self._sections.append((heading, content))

    def add_table(self, headers: list[str], rows: list[list[str]]) -> str:
        """Build a markdown table and return it as a string."""
        if not headers or not rows:
            return ""
        # Header row
        header_line = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join("---" for _ in headers) + " |"
        # Data rows
        data_lines = []
        for row in rows:
            # Pad row to match header length
            padded = row + [""] * (len(headers) - len(row))
            data_lines.append("| " + " | ".join(str(c) for c in padded) + " |")
        return "\n".join([header_line, separator] + data_lines)

    def add_score_card(self, scores: dict[str, float], max_score: float = 10.0) -> str:
        """Build a score card table. Returns markdown string."""
        headers = ["Axis", "Score", "Rating"]
        rows = []
        for axis, score in scores.items():
            pct = score / max_score
            if pct >= 0.8:
                rating = "Excellent"
            elif pct >= 0.6:
                rating = "Good"
            elif pct >= 0.4:
                rating = "Fair"
            else:
                rating = "Needs Work"
            rows.append([axis, f"{score:.1f}/{max_score:.0f}", rating])
        total = sum(scores.values())
        max_total = max_score * len(scores)
        rows.append(["**Total**", f"**{total:.1f}/{max_total:.0f}**", ""])
        return self.add_table(headers, rows)

    def build(self) -> str:
        """Build the full report as a markdown string."""
        lines = [
            f"# {self.title}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for heading, content in self._sections:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)
