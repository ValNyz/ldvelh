"""
Part 5: Automated benchmark runner.
Orchestrates all benchmark parts and produces full_report.md.

Usage:
    cd backend
    python -m tests.benchmark.run_benchmark [--regen-fixture] [--parts 0,1,2,3] [--depth 200]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Paths
BACKEND_DIR = Path(__file__).parent.parent.parent
TESTS_DIR = BACKEND_DIR / "tests"
BENCHMARK_DIR = TESTS_DIR / "benchmark"
REPORTS_DIR = TESTS_DIR / "reports"
FIXTURES_DIR = TESTS_DIR / "fixtures" / "benchmark"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _run_pytest(test_file: str, extra_args: list[str] | None = None) -> dict:
    """Run pytest on a test file and capture results."""
    repo_root = BACKEND_DIR.parent
    cmd = [
        sys.executable, "-m", "pytest",
        str(BENCHMARK_DIR / test_file),
        "-v", "--tb=short",
        f"--rootdir={repo_root}",
    ]
    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Running: {' '.join(cmd)}")
    logger.info(f"{'=' * 60}")

    # Stream output live (no buffering) while capturing for parsing
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # line-buffered
        cwd=str(BACKEND_DIR),
    )

    output_lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        output_lines.append(line)

    proc.wait()
    full_output = "".join(output_lines)

    # Parse results from output — split on \r too since progress uses carriage returns
    all_segments = []
    for line in output_lines:
        all_segments.extend(line.split("\r"))
    passed = sum(1 for s in all_segments if " PASSED" in s)
    failed = sum(1 for s in all_segments if " FAILED" in s)
    skipped = sum(1 for s in all_segments if " SKIPPED" in s)

    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "returncode": proc.returncode,
        "output": full_output,
    }


def run_part0() -> str:
    """Part 0: Static code analysis (qualitative feature inventory)."""
    logger.info("\n" + "=" * 60)
    logger.info("PART 0: Code Analysis (Feature Inventory)")
    logger.info("=" * 60)

    from .code_analyzer import run_analysis, save_report

    features, markdown = run_analysis()
    report_path = save_report()

    logger.info(f"Report saved to: {report_path}")
    for axis, feats in features.items():
        logger.info(f"  {axis}: {len(feats)} features detected")

    return markdown


def run_part1(regen_fixture: bool = False, depth: int = 200, provider: str = "wandb", fixture: str | None = None) -> dict:
    """Part 1: Long-term memory tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PART 1: Long-term Memory Tests")
    logger.info("=" * 60)

    extra_args = ["-m", "benchmark", "--benchmark-provider", provider, "-s"]
    if regen_fixture:
        extra_args.append("--regen-fixture")
    extra_args.extend(["--benchmark-depth", str(depth)])
    if fixture:
        extra_args.extend(["--benchmark-fixture", fixture])

    return _run_pytest("test_memory.py", extra_args)


def run_part2(provider: str = "wandb", fixture: str | None = None) -> dict:
    """Part 2: LLM compliance tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PART 2: LLM Compliance Tests")
    logger.info("=" * 60)

    extra_args = ["-m", "benchmark_llm", "--benchmark-provider", provider, "-s"]
    if fixture:
        extra_args.extend(["--benchmark-fixture", fixture])

    compliance = _run_pytest("test_compliance.py", extra_args)
    narrative = _run_pytest("test_narrative_quality.py", extra_args)

    # Merge results
    return {
        "passed": compliance["passed"] + narrative["passed"],
        "failed": compliance["failed"] + narrative["failed"],
        "skipped": compliance["skipped"] + narrative["skipped"],
        "returncode": max(compliance["returncode"], narrative["returncode"]),
        "output": compliance["output"] + "\n" + narrative["output"],
    }


def run_part3() -> dict:
    """Part 3: Competitor benchmark."""
    logger.info("\n" + "=" * 60)
    logger.info("PART 3: Competitor Benchmark")
    logger.info("=" * 60)

    return _run_pytest("test_benchmark.py", ["-m", "benchmark"])


def generate_full_report(
    code_analysis: str | None,
    memory_results: dict | None,
    compliance_results: dict | None,
    benchmark_results: dict | None,
) -> str:
    """Generate the full benchmark report from all parts."""
    from .report_builder import ReportBuilder

    report = ReportBuilder("LDVELH Full Benchmark Report")

    # Executive summary
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    for results in [memory_results, compliance_results, benchmark_results]:
        if results:
            total_passed += results.get("passed", 0)
            total_failed += results.get("failed", 0)
            total_skipped += results.get("skipped", 0)

    summary = (
        f"**Total tests: {total_passed + total_failed + total_skipped}** "
        f"(passed: {total_passed}, failed: {total_failed}, skipped: {total_skipped})\n\n"
    )
    report.add_section("Executive Summary", summary)

    # Part 0
    if code_analysis:
        report.add_section("Part 0: Code Analysis", code_analysis)

    # Part 1
    if memory_results:
        part1_summary = (
            f"Passed: {memory_results['passed']} | "
            f"Failed: {memory_results['failed']} | "
            f"Skipped: {memory_results['skipped']}"
        )
        report.add_section("Part 1: Long-term Memory", part1_summary)

    # Part 2
    if compliance_results:
        part2_summary = (
            f"Passed: {compliance_results['passed']} | "
            f"Failed: {compliance_results['failed']} | "
            f"Skipped: {compliance_results['skipped']}"
        )
        report.add_section("Part 2: LLM Compliance", part2_summary)

    # Part 3
    if benchmark_results:
        part3_summary = (
            f"Passed: {benchmark_results['passed']} | "
            f"Failed: {benchmark_results['failed']} | "
            f"Skipped: {benchmark_results['skipped']}"
        )
        report.add_section("Part 3: Competitor Comparison", part3_summary)

    # Part 4: Auto-generated recommendations
    recommendations = _generate_recommendations(
        memory_results, compliance_results
    )
    if recommendations:
        report.add_section("Part 4: Recommendations", recommendations)

    return report.build()


def _generate_recommendations(
    memory_results: dict | None, compliance_results: dict | None
) -> str:
    """Auto-generate improvement recommendations from test results."""
    recs = []

    if memory_results and memory_results.get("failed", 0) > 0:
        recs.append(
            "- **Memory**: Some memory tests failed. Consider increasing the "
            "context window or facts limit for better long-term recall."
        )

    if compliance_results and compliance_results.get("failed", 0) > 0:
        recs.append(
            "- **LLM Compliance**: Some compliance tests failed. Consider "
            "strengthening the mechanical enforcement constraints in narrator prompts."
        )

    if not recs:
        recs.append(
            "- All benchmark tests passed. The system performs well across all axes."
        )
        recs.append(
            "- Consider running with `--depth 500` for deeper stress testing."
        )

    return "\n".join(recs)


def main():
    parser = argparse.ArgumentParser(description="LDVELH Benchmark Runner")
    parser.add_argument(
        "--regen-fixture", action="store_true",
        help="Regenerate game dump fixture (requires LLM API key)",
    )
    parser.add_argument(
        "--parts", default="0,1,2,3",
        help="Comma-separated list of parts to run (default: 0,1,2,3)",
    )
    parser.add_argument(
        "--depth", type=int, default=200,
        help="Number of turns for fixture generation (default: 200)",
    )
    parser.add_argument(
        "--provider", default="wandb",
        help="LLM provider for benchmark (default: wandb)",
    )
    parser.add_argument(
        "--fixture", default=None,
        help="Path to game_dump.json fixture (default: auto-detect)",
    )
    args = parser.parse_args()

    parts = [int(p.strip()) for p in args.parts.split(",")]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Run selected parts
    code_analysis = None
    memory_results = None
    compliance_results = None
    benchmark_results = None

    if 0 in parts:
        code_analysis = run_part0()

    if 1 in parts:
        memory_results = run_part1(
            regen_fixture=args.regen_fixture,
            depth=args.depth,
            provider=args.provider,
            fixture=args.fixture,
        )

    if 2 in parts:
        compliance_results = run_part2(provider=args.provider, fixture=args.fixture)

    if 3 in parts:
        benchmark_results = run_part3()

    # Generate full report
    full_report = generate_full_report(
        code_analysis, memory_results, compliance_results, benchmark_results,
    )

    report_path = REPORTS_DIR / "full_report.md"
    report_path.write_text(full_report, encoding="utf-8")
    logger.info(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    main()
