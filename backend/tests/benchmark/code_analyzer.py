"""
Part 0: Static code analysis for LDVELH benchmark.
Produces a qualitative feature inventory organized by 4 axes:
Memory, Coherence, LLM Resistance, Robustness.

No numeric scores — this is a feature report, not a rating.
Actual quality scores come from Part 1 (memory tests) and Part 2 (compliance tests).
"""

from __future__ import annotations

import re
from pathlib import Path

from .report_builder import ReportBuilder

BACKEND_DIR = Path(__file__).parent.parent.parent
SCHEMA_SQL = BACKEND_DIR.parent / "schema.sql"
if not SCHEMA_SQL.exists():
    SCHEMA_SQL = BACKEND_DIR.parent / "db" / "schema.sql"


def _read(path: Path) -> str:
    """Read a file, return empty string if not found."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# =============================================================================
# AXIS 1: MEMORY (context preservation across turns)
# =============================================================================


def _inventory_memory() -> list[dict]:
    """Inventory memory/context preservation features."""
    features = []
    ctx = _read(BACKEND_DIR / "services" / "context_builder.py")

    # History window
    match = re.search(r"max\((\d+),\s*current_cycle\s*-\s*(\d+)\)", ctx)
    if match:
        features.append({
            "feature": "Sliding history window",
            "detail": f"max({match.group(1)}, current_cycle - {match.group(2)}) — "
                      f"{int(match.group(2)) + 1}-cycle conversation window",
            "file": "services/context_builder.py",
        })
    else:
        features.append({
            "feature": "Sliding history window",
            "detail": "NOT DETECTED",
            "file": "services/context_builder.py",
        })

    # NPC tiers
    npc_tiers = []
    if "npcs_requested" in ctx or "detail_request" in ctx:
        npc_tiers.append("requested (full detail)")
    if "npcs_present" in ctx:
        npc_tiers.append("present at location (medium detail)")
    if "all_npcs" in ctx or "_build_all_npcs_light" in ctx:
        npc_tiers.append("all known (name only)")
    if npc_tiers:
        features.append({
            "feature": f"{len(npc_tiers)}-tier NPC detail system",
            "detail": " / ".join(npc_tiers),
            "file": "services/context_builder.py",
        })

    # Facts filter
    facts_match = re.search(r"min_importance=(\d+),\s*limit=(\d+)", ctx)
    if facts_match:
        features.append({
            "feature": "Fact relevance filter",
            "detail": f"importance >= {facts_match.group(1)}, limit {facts_match.group(2)}",
            "file": "services/context_builder.py",
        })

    # Cycle summaries
    summary_match = re.search(r"_build_cycle_summaries.*?limit.*?=\s*(\d+)", ctx, re.DOTALL)
    if summary_match:
        features.append({
            "feature": "Cycle summaries (chronology)",
            "detail": f"Limit {summary_match.group(1)} entries, before conversation window",
            "file": "services/context_builder.py",
        })

    # Info requests
    if "info_requests" in ctx or "detail_request" in ctx:
        features.append({
            "feature": "On-demand detail prefetch",
            "detail": "Narrator can request entity details for next turn",
            "file": "services/context_builder.py",
        })

    # NPC ordering
    if "relation_level" in ctx and "DESC" in ctx:
        features.append({
            "feature": "NPC priority ordering",
            "detail": "By relationship level DESC, arc intensity DESC",
            "file": "services/context_builder.py",
        })

    return features


# =============================================================================
# AXIS 2: COHERENCE (entity dedup and consistency)
# =============================================================================


def _inventory_coherence() -> list[dict]:
    """Inventory entity dedup and consistency features."""
    features = []

    sql = _read(SCHEMA_SQL)
    resolver = _read(BACKEND_DIR / "services" / "extraction" / "resolver.py")
    populator = _read(BACKEND_DIR / "kg" / "specialized_populator.py")

    # DB UNIQUE constraints
    unique_count = len(re.findall(r"UNIQUE\s*\(\s*game_id\s*,\s*name\s*\)", sql, re.IGNORECASE))
    if unique_count > 0:
        features.append({
            "feature": "DB UNIQUE constraints",
            "detail": f"UNIQUE(game_id, name) on {unique_count} entity tables",
            "file": "schema.sql",
        })

    # Entity registry triggers
    trigger_count = len(re.findall(r"CREATE\s+TRIGGER\s+register_", sql, re.IGNORECASE))
    if trigger_count > 0:
        features.append({
            "feature": "Auto-registration triggers",
            "detail": f"{trigger_count} triggers auto-register entities in entity_registry "
                      "with ON CONFLICT DO NOTHING",
            "file": "schema.sql",
        })

    # ON CONFLICT
    on_conflict = len(re.findall(r"ON\s+CONFLICT.*DO\s+(NOTHING|UPDATE)", sql, re.IGNORECASE))
    if on_conflict > 0:
        features.append({
            "feature": "ON CONFLICT dedup clauses",
            "detail": f"{on_conflict} clauses in SQL schema",
            "file": "schema.sql",
        })

    # Phase 1 resolver
    if "resolve_entities" in resolver:
        sub = []
        if "ResolutionMap" in resolver:
            sub.append("ResolutionMap dataclass")
        if "_build_entity_catalog" in resolver:
            sub.append("entity catalog from DB")
        if "_parse_resolution" in resolver:
            sub.append("LLM response parsing")
        features.append({
            "feature": "Phase 1 entity resolver",
            "detail": f"Pre-extraction disambiguation via Haiku LLM call. "
                      f"Components: {', '.join(sub)}",
            "file": "services/extraction/resolver.py",
        })

    # Case-insensitive matching
    if "LOWER(name)" in populator or "canonical_name" in populator.lower():
        features.append({
            "feature": "Case-insensitive name matching",
            "detail": "LOWER(name) in all entity lookups",
            "file": "kg/specialized_populator.py",
        })

    # Immutable facts
    if re.search(r"(immutable|prevent.*update).*fact", sql, re.IGNORECASE):
        features.append({
            "feature": "Immutable facts",
            "detail": "DB trigger prevents UPDATE on facts table",
            "file": "schema.sql",
        })

    # Semantic key dedup
    if "semantic_key" in sql:
        features.append({
            "feature": "Fact semantic dedup",
            "detail": "UNIQUE(game_id, cycle, semantic_key) constraint on facts",
            "file": "schema.sql",
        })

    return features


# =============================================================================
# AXIS 3: LLM RESISTANCE (constraining LLM behavior)
# =============================================================================


def _inventory_llm_resistance() -> list[dict]:
    """Inventory LLM behavior enforcement features."""
    features = []

    engine_base = _read(BACKEND_DIR / "services" / "engine" / "base.py")
    fate_core = _read(BACKEND_DIR / "services" / "engine" / "fate_core.py")
    d6 = _read(BACKEND_DIR / "services" / "engine" / "d6.py")
    routes = _read(BACKEND_DIR / "api" / "routes.py")

    # DEFINITIF constraint
    if "DÉFINITIF" in engine_base or "DEFINITIF" in engine_base:
        features.append({
            "feature": 'Binding mechanical results ("DEFINITIF")',
            "detail": "Mechanical roll outcomes injected into narrator prompt as non-negotiable constraints",
            "file": "services/engine/base.py",
        })

    # Explicit no-override rules
    engines_with_rules = []
    for name, src in [("fate_core", fate_core), ("d6", d6)]:
        if "Tu ne décides PAS" in src or "Tu ne decides PAS" in src:
            engines_with_rules.append(name)
    if engines_with_rules:
        features.append({
            "feature": "Explicit outcome prohibition",
            "detail": f'"Tu ne decides PAS du succes ou de l\'echec" in: {", ".join(engines_with_rules)}',
            "file": "services/engine/{fate_core,d6}.py",
        })

    # Structured output
    narrator = _read(BACKEND_DIR / "prompts" / "narrator_prompt.py")
    if "NarrationOutput" in narrator:
        features.append({
            "feature": "Structured output schema",
            "detail": "NarrationOutput Pydantic model validates all narrator responses",
            "file": "prompts/narrator_prompt.py",
        })

    # Fire-and-forget extraction
    if "create_task" in routes and "run_triggered_extraction" in routes:
        features.append({
            "feature": "Async extraction",
            "detail": "Extraction runs fire-and-forget, never blocks narration",
            "file": "api/routes.py",
        })

    # Engine addons
    addon_engines = []
    for engine_file in ["fate_core.py", "d6.py", "narrative.py"]:
        src = _read(BACKEND_DIR / "services" / "engine" / engine_file)
        if "system_prompt_addon" in src or "RÈGLES" in src:
            addon_engines.append(engine_file.replace(".py", ""))
    if addon_engines:
        features.append({
            "feature": "Engine-specific narrator constraints",
            "detail": f"Custom rules injected by: {', '.join(addon_engines)}",
            "file": "services/engine/*.py",
        })

    # Separate mechanical LLM
    mechanical = _read(BACKEND_DIR / "services" / "engine" / "mechanical_service.py")
    if "run_mechanical_step" in mechanical:
        features.append({
            "feature": "Separate mechanical LLM call",
            "detail": "Haiku decides test/difficulty independently from narrator",
            "file": "services/engine/mechanical_service.py",
        })

    return features


# =============================================================================
# AXIS 4: ROBUSTNESS (error handling, concurrency)
# =============================================================================


def _inventory_robustness() -> list[dict]:
    """Inventory robustness and reliability features."""
    features = []

    routes = _read(BACKEND_DIR / "api" / "routes.py")
    orchestrator = _read(BACKEND_DIR / "services" / "extraction" / "orchestrator.py")

    if "_game_locks" in routes:
        features.append({
            "feature": "Per-game concurrency locks",
            "detail": "asyncio.Lock per game_id prevents concurrent chat processing",
            "file": "api/routes.py",
        })

    if "_extracting_games" in orchestrator:
        features.append({
            "feature": "Extraction concurrency guard",
            "detail": "Set-based guard prevents duplicate extraction runs for same game",
            "file": "services/extraction/orchestrator.py",
        })

    if "continuing without" in orchestrator.lower() or "Phase 1" in orchestrator:
        features.append({
            "feature": "Resolver graceful degradation",
            "detail": "If entity resolver fails, extraction continues without it (same as before resolver existed)",
            "file": "services/extraction/orchestrator.py",
        })

    try_except_count = len(re.findall(r"except\s+(Exception|.*Error)", routes))
    if try_except_count > 0:
        features.append({
            "feature": "Error boundaries",
            "detail": f"{try_except_count} exception handlers in main route handler",
            "file": "api/routes.py",
        })

    if "checkpoint" in orchestrator.lower():
        features.append({
            "feature": "Extraction checkpoints",
            "detail": "Idempotent extraction reruns via per-extractor cycle checkpoints",
            "file": "services/extraction/orchestrator.py",
        })

    if "send_error" in routes and "recoverable" in routes:
        features.append({
            "feature": "SSE error recovery",
            "detail": "Frontend notified of recoverable errors via SSE stream",
            "file": "api/routes.py",
        })

    if "rate_limit" in routes or "limiter" in routes:
        features.append({
            "feature": "Rate limiting",
            "detail": "API endpoint rate limiting",
            "file": "api/routes.py",
        })

    return features


# =============================================================================
# MAIN
# =============================================================================


def run_analysis() -> tuple[dict[str, list[dict]], str]:
    """Run the full code analysis.

    Returns:
        (features_by_axis, markdown_report)
    """
    axes = {
        "Memory": _inventory_memory,
        "Coherence": _inventory_coherence,
        "LLM Resistance": _inventory_llm_resistance,
        "Robustness": _inventory_robustness,
    }

    all_features = {}
    report = ReportBuilder("LDVELH Code Analysis — Feature Inventory")

    # Summary table
    summary_rows = []
    for axis_name, inventory_fn in axes.items():
        features = inventory_fn()
        all_features[axis_name] = features
        summary_rows.append([axis_name, str(len(features)), ", ".join(f["feature"] for f in features[:3])])

    summary_table = report.add_table(
        ["Axis", "Features Found", "Key Features"],
        summary_rows,
    )
    report.add_section("Feature Summary", summary_table)

    # Detailed inventory per axis
    for axis_name, features in all_features.items():
        if not features:
            report.add_section(axis_name, "No features detected.")
            continue

        rows = [[f["feature"], f["detail"], f["file"]] for f in features]
        table = report.add_table(["Feature", "Detail", "File"], rows)
        report.add_section(axis_name, table)

    # Gaps / missing features
    gaps = _identify_gaps(all_features)
    if gaps:
        report.add_section("Identified Gaps", "\n".join(f"- {g}" for g in gaps))

    return all_features, report.build()


def _identify_gaps(features: dict[str, list[dict]]) -> list[str]:
    """Identify missing or weak features based on the inventory."""
    gaps = []

    memory_names = {f["feature"] for f in features.get("Memory", [])}
    if "Sliding history window" not in memory_names:
        gaps.append("No sliding history window for multi-turn context")
    # Check for saliency scoring (not currently implemented)
    gaps.append("No algorithmic saliency scoring — NPC/fact relevance is implicit via DB ordering")

    coherence_names = {f["feature"] for f in features.get("Coherence", [])}
    if "Phase 1 entity resolver" not in coherence_names:
        gaps.append("No pre-extraction entity disambiguation")

    resistance_names = {f["feature"] for f in features.get("LLM Resistance", [])}
    if not any("DEFINITIF" in f["feature"] for f in features.get("LLM Resistance", [])):
        gaps.append("No binding mechanical result injection")

    return gaps


def save_report(output_path: Path | None = None) -> Path:
    """Run analysis and save the report to disk."""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "reports" / "code_analysis.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _, markdown = run_analysis()
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = save_report()
    print(f"Report saved to {path}")
