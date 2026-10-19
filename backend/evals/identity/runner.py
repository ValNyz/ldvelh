"""Runs a resolver adapter over the corpus, scores it and writes the report (#151).

Used by scripts/eval_identity.py. Scenes are scored on their narration gold; sequences
only feed B³ / CEAF-e. C@10 is measured on dev + test in one run (spec § 3.5) when the
adapter can give its candidates without a resolver run (`Adapter.candidates`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from evals.identity.corpus import (
    Scene,
    Sequence,
    load_scenes,
    load_sequences,
    load_split,
)
from evals.identity.report import render
from evals.identity.run import RunResult
from evals.identity.scorer import SceneScore, score_scene

if TYPE_CHECKING:
    from evals.identity.adapters.base import Adapter
    from llm.session import LLMSession

SessionFor = Callable[[str], "LLMSession | None"]  # scene id -> session of its call


@dataclass(frozen=True)
class Selection:
    scenes: list[Scene]
    sequences: list[Sequence]

    @property
    def requests(self) -> list[Scene]:
        """Every scene a resolver call is made for: scenes, then sequence turns."""
        return [*self.scenes, *(t for q in self.sequences for t in q.turns)]


def select(
    root: Path,
    split: str,
    *,
    category: str | None = None,
    scene_id: str | None = None,
    sequences: bool = False,
) -> Selection:
    """Scenes of `split`, optionally one scene or those with a gold of `category`.

    Sequences are not in the split (no test narration appears in one, ANNOTATION § 8):
    `sequences` adds all of them.
    """
    ids = set(getattr(load_split(root), split))
    scenes = [s for s in load_scenes(root) if s.id in ids]
    if scene_id is not None:
        scenes = [s for s in scenes if s.id == scene_id]
    if category is not None:
        scenes = [s for s in scenes if any(m.category == category for m in s.gold)]
    return Selection(scenes, load_sequences(root) if sequences else [])


async def run_scenes(
    adapter: Adapter, scenes: list[Scene], session_for: SessionFor, pool=None
) -> list[RunResult]:
    results = []
    for scene in scenes:
        adapter.begin_sequence()
        results.append(
            await adapter.run_scene(scene, session=session_for(scene.id), pool=pool)
        )
    return results


async def run_sequences(
    adapter: Adapter, sequences: list[Sequence], session_for: SessionFor, pool=None
) -> list[tuple[Sequence, list[RunResult]]]:
    runs = []
    for sequence in sequences:
        adapter.begin_sequence()
        results = [
            await adapter.run_scene(turn, session=session_for(turn.id), pool=pool)
            for turn in sequence.turns
        ]
        runs.append((sequence, results))
    return runs


def score(scenes: list[Scene], results: list[RunResult]) -> list[SceneScore]:
    by_id = {r.scene_id: r for r in results}
    return [score_scene(scene, by_id[scene.id]) for scene in scenes]


async def blocking_scores(adapter: Adapter, root: Path) -> list[SceneScore] | None:
    """C@10 scores of the adapter's blocking on dev + test (None if it has none)."""
    split = load_split(root)
    ids = set(split.dev) | set(split.test)
    scores = []
    for scene in (s for s in load_scenes(root) if s.id in ids):
        candidates = await adapter.candidates(scene)
        if candidates is None:
            return None
        scores.append(score_scene(scene, RunResult(scene.id, [], candidates, {})))
    return scores


def report_name(
    date: str,
    split: str,
    provider: str,
    models: dict[str, str],
    responder: str | None = None,
) -> str:
    """`<date>-<split>-<provider>-<models>`, plus the responder kind (the text before
    `:`) when the answers did not come from the API."""
    name = f"{date}-{split}-{provider}-{'+'.join(models.values()) or 'none'}"
    if responder:
        name += f"-{responder.split(':', 1)[0]}"
    return re.sub(r"[^\w.+-]", "_", name)


def write_report(out: Path, name: str, markdown: str, data: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.md"
    path.write_text(markdown, encoding="utf-8")
    (out / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def build_report(
    scores_by_run: list[list[SceneScore]],
    *,
    provider: str,
    models: dict[str, str],
    split: str,
    header_note: str = "",
    responder: str | None = None,
    sequence_results_by_run=None,
    c_at_10_scores: list[SceneScore] | None = None,
    iterations: int = 2000,
) -> tuple[str, dict]:
    """`report.render`, with `responder` (who answered, None for API calls) in the json."""
    markdown, data = render(
        scores_by_run,
        provider=provider,
        models=models,
        split=split,
        header_note=header_note,
        sequence_results_by_run=sequence_results_by_run or None,
        c_at_10_scores=c_at_10_scores,
        iterations=iterations,
    )
    return markdown, {**data, "responder": responder}
