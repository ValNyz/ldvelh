"""Identity evaluation report, markdown + json (#151, spec § 3.5 and § 3.6).

`render` takes the `SceneScore`s of each run (same scenes in every run) and prints:
the D25 caveat header, the § 3.5 gate table (threshold, mean of the runs, 95 % bootstrap
interval, verdict), the hard categories absent from the scores, both readings of the
per-category floors (0.85; 0.88 once every hard category has 60 test mentions), the
spurious-decision rates and NEW type errors, the category x type table, the cheap tier
alone, the deterministic share, the cost per turn, and B³/CEAF-e on sequences.

One estimator for the verdict and the interval: a row's value is the metric of the
POOLED scores of all runs (`aggregate(run1 + run2 + run3)`, equal to the mean of the runs
when every run scores the same scenes), and its interval resamples those pooled scores
by whole scenes (bootstrap.ci); the per-run values are kept in the json. A row that
cannot be computed fails. Bootstrap draws where a row is undefined (a category absent
from the draw) are dropped by bootstrap.ci; the report counts them per row and prints
them, so a narrow interval on few valid draws is visible. C@10 is defined on dev + test
in one run (spec § 3.5): the runner passes those scores as `c_at_10_scores`; without
them the row falls back on the runs of this report, and the source is printed. R and P
(knowledge checks, § 3.4 bis) are not measured here; L is when the runner gives the
leaks of each run (`leaks_by_run`, evals/identity/leaks.py), a gate row whose value is
the total. `gate_passed` covers the measured rows only and `gate_complete` stays false.
A milestone gate (`milestone`, MILESTONES: the PR 2 gate of the plan) reuses the
measured rows with its own thresholds and prints the escalation rate and the cost per
turn against their targets. The cost is the API's (`cost_measured`), estimated from
the replayed calls (`cost_estimated`), or unavailable when a model has no price
(`cost_priced` false); the tokens are printed either way. B³ is reported, not gated, until
PR 5. The report is written in French, like the spec it is read against.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from config import get_identity_config
from evals.identity import bootstrap, coref
from evals.identity.corpus import HARD_CATEGORIES
from evals.identity.scorer import Metrics, SceneScore, aggregate
from evals.identity.split import CATEGORY_ORDER

if TYPE_CHECKING:
    from evals.identity.corpus import Sequence
    from evals.identity.run import RunResult

CAVEAT = "chiffres = accord avec l'annotateur unique, plafond humain non mesuré"
DEFAULT_THRESHOLDS = {
    "hard_macro": 0.90,
    "hard_pool": 0.90,
    "hard_category": 0.85,  # indicative floor
    "hard_category_binding": 0.88,  # binding floor, with enough test mentions
    "binding_min_mentions": 60,
    "easy_pool": 0.97,
    "W": 0.02,
    "D": 0.08,
    "c_at_10": 0.98,
    "b_cubed": 0.85,  # reported, gated from PR 5
}
MIN_TYPE_SHARE = 0.15  # spec § 3.2: no type under 15 % of the hard mentions
OK, FAIL = "OK", "ÉCHEC"
C_AT_10_SOURCES = {
    "dev + test, 1 run": "blocage sur dev + test, 1 exécution (spec § 3.5)",
    "runs of this report": "sur les exécutions de ce rapport (la spec le définit "
    "sur dev + test, 1 exécution)",
}
NOT_MEASURED = (
    ("R", "Révélations correctes R", "≥ 0,90"),
    ("P", "Erreurs de point de vue P", "≤ 0,05"),
    ("L", "Fuites de secrets L", "= 0"),
)
LEAK_LABEL = "Fuites de secrets L"
# Milestone gates of the plan: rows (gate row name, threshold) and the cost target per
# turn; the escalation target is IdentityConfig.escalation_target_rate.
MILESTONES = {
    "pr2": {
        "label": "PR 2",
        "rows": (("hard_pool", 0.85), ("W", 0.02), ("L", 0)),
        "cost_target_usd": 0.01,
    },
}
ESTIMATE_NOTE = "estimé : jetons ≈ caractères / 4, sans cache ni réflexion"
# (name, label, threshold key, operator, extractor)
GLOBAL_ROWS: tuple[tuple[str, str, str, str, Callable[[Metrics], float]], ...] = (
    ("hard_macro", "Macro-moyenne A_cat (6 catégories dures)", "hard_macro", ">=",
     lambda m: m.hard_macro),
    ("hard_pool", "Accuracy groupée, mentions dures (pool)", "hard_pool", ">=",
     lambda m: m.hard_pool.value),
    ("easy_pool", "Accuracy EASY + PC + SKIP", "easy_pool", ">=",
     lambda m: m.easy_pool.value),
    ("W", "W fusions abusives", "W", "<=", lambda m: m.W),
    ("D", "D doublons", "D", "<=", lambda m: m.D),
    ("c_at_10", "C@10 blocage", "c_at_10", ">=", lambda m: m.c_at_10),
)  # fmt: skip
RATES = (
    ("spurious_link_per_turn", "Fusions parasites par tour (MATCH/ALIAS hors or)"),
    ("spurious_new_per_turn", "NEW parasites par tour (hors or)"),
    ("new_type_errors", "Erreurs de type NEW (par exécution)"),
    ("new_precision", "Précision du NEW"),
    ("new_recall", "Rappel du NEW"),
    ("unsure_rate", "Taux d'UNSURE"),
)


# --- numbers ----------------------------------------------------------------


def _mean(values: list[float]) -> float:
    if not values or any(math.isnan(v) for v in values):
        return math.nan
    return sum(values) / len(values)


def _fmt(value: float | None) -> str:
    if isinstance(value, int):
        return str(value)
    if value is None or math.isnan(value):
        return "—"
    return f"{value:.3f}".replace(".", ",")


def _fmt_limit(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _fmt_amount(value: float) -> str:
    """Tokens, calls or dollars: 4 significant digits (2000, 1,5, 0,005)."""
    return "—" if math.isnan(value) else f"{value:.4g}".replace(".", ",")


def _fmt_ci(interval: tuple[float, float]) -> str:
    low, high = interval
    return "—" if math.isnan(low) else f"[{_fmt(low)} ; {_fmt(high)}]"


def _verdict(value: float, op: str, threshold: float) -> str:
    if math.isnan(value):
        return FAIL
    passed = {
        ">=": value >= threshold,
        "<=": value <= threshold,
        "==": value == threshold,
    }
    return OK if passed[op] else FAIL


def _clean(value):
    """JSON-safe copy: nan -> None, tuples -> lists."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


class _Aggregator:
    """`aggregate` memoised on the drawn scores: every row's bootstrap uses the same
    seed, hence the same draws, so each replicate is aggregated once for all rows."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, ...], Metrics] = {}

    def __call__(self, scores: list[SceneScore]) -> Metrics:
        key = tuple(map(id, scores))
        if key not in self._cache:
            self._cache[key] = aggregate(scores)
        return self._cache[key]


# --- gate rows --------------------------------------------------------------


def _row(name, label, op, threshold, extract, ctx, source: str = "runs") -> dict:
    """One gate row on `ctx[source]` = (per-run metrics, pooled scores)."""
    metrics, pooled = ctx[source]
    value = extract(ctx["aggregate"](pooled))
    undefined = 0

    def replicate(scores: list[SceneScore]) -> float:
        nonlocal undefined
        result = extract(ctx["aggregate"](scores))
        undefined += math.isnan(result)
        return result

    interval = bootstrap.ci(pooled, replicate, iterations=ctx["iterations"])
    return {
        "name": name,
        "label": label,
        "op": op,
        "threshold": threshold,
        "estimator": "pooled",
        "per_run": [extract(m) for m in metrics],
        "value": value,
        "ci": list(interval),
        "undefined_draws": undefined,
        "verdict": _verdict(value, op, threshold),
    }


def _category_extract(category: str) -> Callable[[Metrics], float]:
    def extract(m: Metrics) -> float:
        acc = m.by_category.get(category)
        return acc.value if acc is not None else math.nan

    return extract


def _floors(ctx: dict, thresholds: dict) -> dict:
    first = ctx["runs"][0][0].by_category
    mentions = {c: first[c].total if c in first else 0 for c in HARD_CATEGORIES}
    minimum = thresholds["binding_min_mentions"]
    applies = all(n >= minimum for n in mentions.values())
    rows = {
        c: _row(f"A_{c}", f"A_{c}", ">=", thresholds["hard_category"],
                _category_extract(c), ctx)
        for c in HARD_CATEGORIES
    }  # fmt: skip
    binding = thresholds["hard_category_binding"]
    return {
        "test_mentions": mentions,
        "rows": rows,
        "indicative": {
            "threshold": thresholds["hard_category"],
            "verdicts": {c: r["verdict"] for c, r in rows.items()},
        },
        "binding": {
            "threshold": binding,
            "min_mentions": minimum,
            "applies": applies,
            "verdicts": {
                c: _verdict(r["value"], ">=", binding) for c, r in rows.items()
            },
        },
    }


def _leak_row(leaks_by_run: list[int]) -> dict:
    """L: the secret names leaked, summed over the runs (no interval: a count)."""
    total = sum(leaks_by_run)
    return {
        "name": "L",
        "label": LEAK_LABEL,
        "op": "==",
        "threshold": 0,
        "estimator": "sum",
        "per_run": list(leaks_by_run),
        "value": total,
        "ci": [math.nan, math.nan],
        "undefined_draws": 0,
        "verdict": _verdict(total, "==", 0),
    }


def _gate(ctx: dict, thresholds: dict) -> tuple[list[dict], dict]:
    rows = [
        _row(name, label, op, thresholds[key], extract, ctx,
             "c_at_10" if name == "c_at_10" else "runs")
        for name, label, key, op, extract in GLOBAL_ROWS
    ]  # fmt: skip
    floors = _floors(ctx, thresholds)
    reading = "binding" if floors["binding"]["applies"] else "indicative"
    for category, row in floors["rows"].items():
        row = dict(row, threshold=floors[reading]["threshold"])
        row["verdict"] = floors[reading]["verdicts"][category]
        row["label"] = f"Catégorie dure {category} seule"
        rows.insert(-4, row)  # after the hard pool, before EASY, as in § 3.5
    return rows, floors


# --- other sections ---------------------------------------------------------


def _category_type(pooled_metrics: Metrics, runs: int) -> tuple[dict, dict]:
    table: dict[str, dict[str, dict]] = {}
    hard_by_type: Counter = Counter()
    for (category, entity_type), acc in sorted(pooled_metrics.by_category_type.items()):
        table.setdefault(category, {})[entity_type] = {
            "accuracy": acc.value,
            "mentions": acc.total // runs,
        }
        if category in HARD_CATEGORIES:
            hard_by_type[entity_type] += acc.total
    total = sum(hard_by_type.values())
    shares = {t: n / total for t, n in sorted(hard_by_type.items())} if total else {}
    return table, shares


def _summary(metrics: list[Metrics]) -> dict:
    return {
        name: _mean([extract(m) for m in metrics])
        for name, _, _, _, extract in GLOBAL_ROWS
    }


def _rates(metrics: list[Metrics]) -> dict:
    names = [name for name, _ in RATES] + ["deterministic_share", "escalation_rate"]
    return {name: _mean([float(getattr(m, name)) for m in metrics]) for name in names}


def _cost(metrics: list[Metrics]) -> dict:
    keys = sorted({k for m in metrics for k in m.cost})
    return {k: _mean([m.cost.get(k, 0.0) for m in metrics]) for k in keys}


def _coref(sequence_results_by_run, iterations: int) -> dict | None:
    if not sequence_results_by_run:
        return None
    b3, ceaf = [], []  # (sequence id, value) of every run
    for run in sequence_results_by_run:
        for sequence, results in run:
            gold = coref.gold_clusters(sequence)
            system = coref.system_clusters(sequence, results)
            b3.append((sequence.id, coref.b_cubed(gold, system)[2]))
            ceaf.append((sequence.id, coref.ceaf_e(gold, system)))

    def line(values: list[tuple[str, float]]) -> dict:
        def mean(vs):
            return _mean([v for _, v in vs])

        interval = bootstrap.ci(values, mean, iterations=iterations, key=lambda v: v[0])
        return {"mean": mean(values), "ci": list(interval)}

    return {
        "sequences": len(sequence_results_by_run[0]),
        "b_cubed": line(b3),
        "ceaf_e": line(ceaf),
    }


# --- markdown ---------------------------------------------------------------


def _op_text(op: str, threshold: float) -> str:
    if op == "==":
        return f"= {threshold}"
    return f"{'≥' if op == '>=' else '≤'} {_fmt_limit(threshold)}"


def _md_header(data: dict) -> list[str]:
    models = ", ".join(f"{k}={v}" for k, v in data["models"].items()) or "—"
    lines = [
        f"# Évaluation identité — split `{data['split']}` — {data['provider']}",
        "",
        f"Modèles : {models} · exécutions : {data['runs']} · scènes : {data['scenes']}",
        "",
        f"> **Avertissement (D25)** : {CAVEAT}.",
    ]
    if data["header_note"]:
        lines.append(f"> {data['header_note']}")
    return lines


def _md_gate(data: dict, rows: list[dict], b_cubed_threshold: float) -> list[str]:
    runs = data["runs"]
    lines = [
        "",
        "## Gate (spec § 3.5)",
        "",
        (
            f"| Condition | Seuil | Valeur ({runs} exéc. groupées) "
            "| IC 95 % (bootstrap par scène) | Verdict |"
        ),
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} | {_op_text(r['op'], r['threshold'])} | {_fmt(r['value'])} "
            f"| {_fmt_ci(r['ci'])} | {r['verdict']} |"
        )
    for item in data["not_measured"]:
        lines.append(
            f"| {item['label']} | {item['threshold']} | — | — | non mesuré ici (§ 3.4 bis) |"
        )
    coref_data = data["coref"]
    b3 = coref_data["b_cubed"] if coref_data else {"mean": None, "ci": [math.nan] * 2}
    lines.append(
        f"| B³ moyen sur les séquences | ≥ {_fmt_limit(b_cubed_threshold)} | {_fmt(b3['mean'])} "
        f"| {_fmt_ci(b3['ci'])} | rapporté (gate à partir de la PR 5) |"
    )
    missing = data["missing_hard_categories"]
    verdict = OK if data["gate_passed"] else FAIL
    unmeasured = ", ".join(item["name"] for item in data["not_measured"])
    lines += [
        "",
        (
            f"**Gate des conditions mesurées ici : {verdict} ; gate incomplète "
            f"({unmeasured} non mesurés).**"
        ),
        f"C@10 : {C_AT_10_SOURCES[data['c_at_10_source']]}.",
    ]
    lines += _md_undefined_draws(rows, data["iterations"])
    if missing:
        lines.append(
            f"Catégories dures absentes : {', '.join(missing)} ; la macro-moyenne "
            "n'est pas calculable (échec), moyenne des catégories présentes : "
            f"{_fmt(data['hard_macro_present'])}."
        )
    else:
        lines.append("Catégories dures absentes : aucune.")
    return lines


def _md_undefined_draws(rows: list[dict], iterations: int) -> list[str]:
    undefined = [r for r in rows if r["undefined_draws"]]
    if not undefined:
        return ["IC : la mesure est définie sur tous les tirages."]
    parts = ", ".join(
        f"{r['name']} {r['undefined_draws']}/{iterations}" for r in undefined
    )
    return [
        (
            "IC calculés sur les seuls tirages où la mesure est définie ; tirages "
            f"indéfinis (catégorie absente du tirage) : {parts}."
        )
    ]


def _md_floors(floors: dict, split: str) -> list[str]:
    ind, bind = floors["indicative"], floors["binding"]
    applies = "s'applique" if bind["applies"] else "ne s'applique pas"
    lines = [
        "",
        "## Planchers par catégorie dure : les deux lectures",
        "",
        f"- Lecture indicative : plancher {_fmt_limit(ind['threshold'])}, lu avec son IC large.",
        (
            f"- Lecture contraignante : plancher {_fmt_limit(bind['threshold'])} si chaque "
            f"catégorie dure a ≥ {bind['min_mentions']} mentions en test ; elle "
            f"{applies} à ce corpus."
        ),
        "",
        (
            f"| Catégorie | Mentions {split} | Moyenne | IC 95 % "
            f"| Plancher {_fmt_limit(ind['threshold'])} | Plancher {_fmt_limit(bind['threshold'])} |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for category, row in floors["rows"].items():
        lines.append(
            f"| {category} | {floors['test_mentions'][category]} | {_fmt(row['value'])} "
            f"| {_fmt_ci(row['ci'])} | {ind['verdicts'][category]} "
            f"| {bind['verdicts'][category]} |"
        )
    return lines


def _md_rates(data: dict) -> list[str]:
    rates = data["rates"]
    lines = ["", "## Décisions parasites et NEW", ""]
    lines += [f"- {label} : {_fmt(rates[name])}" for name, label in RATES]
    lines.append(
        "- Une fusion parasite ne compte dans W que si elle contredit une mention or."
    )
    return lines


def _md_category_type(data: dict) -> list[str]:
    table, shares = data["category_type"], data["hard_type_shares"]
    types = sorted({t for row in table.values() for t in row})
    lines = [
        "",
        "## Catégorie × type (accuracy, mentions par exécution)",
        "",
        "| Catégorie | " + " | ".join(types) + " |",
        "|---" * (len(types) + 1) + "|",
    ]
    for category in [c for c in CATEGORY_ORDER if c in table]:
        cells = [
            f"{_fmt(cell['accuracy'])} ({cell['mentions']})" if cell else "—"
            for cell in (table[category].get(t) for t in types)
        ]
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    under = [t for t, share in shares.items() if share < MIN_TYPE_SHARE]
    share_text = ", ".join(f"{t} {_fmt(s)}" for t, s in shares.items()) or "—"
    lines += ["", f"Part de chaque type dans les mentions dures : {share_text}."]
    if under:
        lines.append(
            f"Types sous {_fmt_limit(MIN_TYPE_SHARE)} des mentions dures : {', '.join(under)}."
        )
    return lines


def _md_cheap(data: dict) -> list[str]:
    cheap = data["cheap_tier"]
    lines = ["", "## Étage bon marché seul", ""]
    if cheap is None:
        return [*lines, "Résultat de l'étage bon marché seul : non exécuté."]
    parts = ", ".join(f"{label} {_fmt(cheap[name])}" for name, label in (
        ("hard_pool", "pool dur"), ("hard_macro", "macro dure"),
        ("easy_pool", "EASY+PC+SKIP"), ("W", "W"), ("D", "D"),
    ))  # fmt: skip
    return [*lines, f"Résultat de l'étage bon marché seul : {parts}."]


def _per_turn(data: dict, key: str) -> float:
    return data["cost"].get(f"per_turn_{key}", math.nan)


def _cost_text(data: dict) -> str:
    """The cost per turn: the API's, estimated from replayed calls, or why not."""
    if not (data["cost_measured"] or data["cost_estimated"]):
        return "non mesuré (réponses importées)"
    if not data["cost_priced"]:
        return "indisponible (modèle sans prix connu)"
    amount = _per_turn(data, "cost_usd")
    text = "—" if math.isnan(amount) else f"{_fmt_amount(amount)} $"
    return f"{text} ({ESTIMATE_NOTE})" if data["cost_estimated"] else text


def _calls_text(data: dict) -> str:
    """Calls per turn, and per stage when the usage names the stages."""
    prefix, suffix = "per_turn_", "_calls"
    stages = sorted(
        k[len(prefix) : -len(suffix)]
        for k in data["cost"]
        if k.startswith(prefix) and k.endswith(suffix) and k != f"{prefix}calls"
    )
    total = _fmt_amount(_per_turn(data, "calls"))
    if not stages:
        return total
    parts = ", ".join(f"{s} {_fmt_amount(_per_turn(data, s + suffix))}" for s in stages)
    return f"{total} ({parts})"


def _escalation(data: dict) -> float:
    """Turns where the strong model was called (`escalated` usage), else turns with an
    escalated decision."""
    rate = _per_turn(data, "escalated")
    return data["rates"]["escalation_rate"] if math.isnan(rate) else rate


def _md_cost(data: dict) -> list[str]:
    tokens = (
        f"entrée {_fmt_amount(_per_turn(data, 'input_tokens'))}, "
        f"sortie {_fmt_amount(_per_turn(data, 'output_tokens'))}"
    )
    if data["cost_estimated"]:
        tokens += f" ({ESTIMATE_NOTE})"
    return [
        "",
        "## Cascade et coût",
        "",
        f"- Part déterministe des décisions : {_fmt(data['rates']['deterministic_share'])}",
        f"- Taux d'escalade (tours) : {_fmt(_escalation(data))}",
        f"- Appels par tour : {_calls_text(data)}",
        f"- Jetons par tour : {tokens}",
        f"- Coût par tour : {_cost_text(data)}",
    ]


def _milestone(spec: dict, rows: list[dict], data: dict) -> dict:
    """The milestone's rows (the measured rows under its thresholds; an unmeasured one
    fails) and its reported targets."""
    by_name = {r["name"]: r for r in rows}
    out = []
    for name, threshold in spec["rows"]:
        row = by_name.get(name)
        if row is None:
            out.append({"name": name, "threshold": threshold, "value": None,
                        "verdict": FAIL, "measured": False})  # fmt: skip
            continue
        verdict = _verdict(row["value"], row["op"], threshold)
        out.append(
            {**row, "threshold": threshold, "verdict": verdict, "measured": True}
        )
    priced = data["cost_priced"] and (data["cost_measured"] or data["cost_estimated"])
    return {
        "label": spec["label"],
        "rows": out,
        "passed": all(r["verdict"] == OK for r in out),
        "escalation_rate": _escalation(data),
        "escalation_target": get_identity_config().escalation_target_rate,
        "cost_per_turn_usd": _per_turn(data, "cost_usd") if priced else None,
        "cost_target_usd": spec["cost_target_usd"],
    }


def _md_milestone(data: dict) -> list[str]:
    gate = data["milestone"]
    if gate is None:
        return []
    lines = [
        "",
        f"## Gate du jalon {gate['label']}",
        "",
        "| Condition | Seuil | Valeur | IC 95 % | Verdict |",
        "|---|---|---|---|---|",
    ]
    for r in gate["rows"]:
        if not r["measured"]:
            lines.append(
                f"| {r['name']} | {r['threshold']} | — | — | {FAIL} (non mesuré) |"
            )
            continue
        lines.append(
            f"| {r['label']} | {_op_text(r['op'], r['threshold'])} | {_fmt(r['value'])} "
            f"| {_fmt_ci(r['ci'])} | {r['verdict']} |"
        )
    lines += [
        (
            f"| Taux d'escalade (tours) | cible ≤ {_fmt_limit(gate['escalation_target'])} "
            f"| {_fmt(gate['escalation_rate'])} | — | rapporté |"
        ),
        (
            f"| Coût par tour | cible ≤ {_fmt_limit(gate['cost_target_usd'])} $ "
            f"| {_cost_text(data)} | — | rapporté |"
        ),
        "",
        f"**Gate du jalon {gate['label']} : {OK if gate['passed'] else FAIL}.**",
    ]
    return lines


def _md_coref_line(label: str, line: dict) -> str:
    return f"- {label} : {_fmt(line['mean'])} {_fmt_ci(line['ci'])}"


def _md_coref(data: dict) -> list[str]:
    coref_data = data["coref"]
    lines = ["", "## Séquences (B³, CEAF-e)", ""]
    if coref_data is None:
        return [*lines, "Séquences : non exécutées."]
    return [
        *lines,
        f"- Séquences : {coref_data['sequences']}",
        _md_coref_line("B³ F1 moyen", coref_data["b_cubed"]),
        _md_coref_line("CEAF-e moyen", coref_data["ceaf_e"]),
    ]


# --- entry point ------------------------------------------------------------


def render(
    scores_by_run: list[list[SceneScore]],
    *,
    provider: str,
    models: dict[str, str],
    split: str,
    thresholds: dict | None = None,
    header_note: str = "",
    cheap_scores_by_run: list[list[SceneScore]] | None = None,
    sequence_results_by_run: list[list[tuple[Sequence, list[RunResult]]]] | None = None,
    c_at_10_scores: list[SceneScore] | None = None,
    iterations: int = 2000,
    cost_measured: bool = True,
    cost_estimated: bool = False,
    cost_priced: bool = True,
    leaks_by_run: list[int] | None = None,
    milestone: str | None = None,
) -> tuple[str, dict]:
    """Markdown report and its json data (nan as null). See the module doc.

    `cost_measured` is False when the answers were imported (no API usage to count);
    `cost_estimated` when their usage was estimated from the replayed calls.
    """
    if not scores_by_run or not all(scores_by_run):
        raise ValueError("render needs at least one run with scored scenes")
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    metrics = [aggregate(run) for run in scores_by_run]
    pooled = [s for run in scores_by_run for s in run]
    blocking = c_at_10_scores or None
    ctx = {
        "runs": (metrics, pooled),
        "c_at_10": ([aggregate(blocking)], blocking) if blocking else (metrics, pooled),
        "iterations": iterations,
        "aggregate": _Aggregator(),
    }
    rows, floors = _gate(ctx, limits)
    if leaks_by_run is not None:
        rows.append(_leak_row(leaks_by_run))
    measured = {r["name"] for r in rows}
    table, shares = _category_type(aggregate(pooled), len(scores_by_run))
    cheap = [aggregate(run) for run in cheap_scores_by_run or []]
    data = {
        "provider": provider,
        "models": dict(models),
        "split": split,
        "runs": len(scores_by_run),
        "scenes": len(scores_by_run[0]),
        "caveat": CAVEAT,
        "header_note": header_note,
        "thresholds": limits,
        "gate": rows,
        "gate_passed": all(r["verdict"] == OK for r in rows),
        "gate_complete": False,  # R, P, L are not measured by this report
        "c_at_10_source": "dev + test, 1 run" if blocking else "runs of this report",
        "iterations": iterations,
        "not_measured": [
            {"name": n, "label": label, "threshold": t}
            for n, label, t in NOT_MEASURED
            if n not in measured
        ],
        "missing_hard_categories": list(metrics[0].hard_categories_missing),
        "hard_macro_present": _mean([m.hard_macro_present for m in metrics]),
        "floors": {k: v for k, v in floors.items() if k != "rows"},
        "category_type": table,
        "hard_type_shares": shares,
        "rates": _rates(metrics),
        "cost": _cost(metrics),
        "cost_measured": cost_measured,
        "cost_estimated": cost_estimated,
        "cost_priced": cost_priced,
        "cheap_tier": _summary(cheap) if cheap else None,
        "coref": _coref(sequence_results_by_run, iterations),
    }
    data["milestone"] = (
        _milestone(MILESTONES[milestone], rows, data) if milestone else None
    )
    lines = _md_header(data)
    lines += _md_gate(data, rows, limits["b_cubed"])
    lines += _md_milestone(data)
    lines += _md_floors(floors, split)
    lines += _md_rates(data)
    lines += _md_category_type(data)
    lines += _md_cheap(data)
    lines += _md_cost(data)
    lines += _md_coref(data)
    return "\n".join(lines) + "\n", _clean(data)
