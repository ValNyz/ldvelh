"""What the identity eval runner needs from a resolver under evaluation (#151)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from evals.identity.corpus import Scene
    from evals.identity.run import RunResult
    from llm.session import LLMSession


class Adapter(Protocol):
    name: str
    sequence_note: str  # caveat for the report header when sequences run ("" if none)
    needs_db: bool  # reads the database (TEST_DATABASE_URL): scripts/eval-identity.sh

    async def run_scene(
        self, scene: Scene, *, session: LLMSession | None, pool
    ) -> RunResult:
        """Decisions and candidates of the resolver on `scene`'s narration."""
        ...

    def begin_sequence(self) -> None:
        """Forget the entities created so far. The runner calls it before each scene,
        and once before the first turn of a sequence (its turns share their creations)."""
        ...

    async def candidates(self, scene: Scene) -> dict[int, list[str]] | None:
        """Blocking candidates per gold start without running the resolver (the C@10 run
        on dev + test), or None when they only come out of a run."""
        ...
