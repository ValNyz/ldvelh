"""Generate fixtures/legacy_game.sql: a Fate game with world, 3 turns and a roll, dumped as INSERTs.

Not collected by CI (name is not test_*.py). Run once by explicit path, on the
pre-refactor code, against the ci-pg container:
  python -m pytest tests/characterization/make_legacy_fixture.py -q -s
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

from services.engine import fate_core
from tests.characterization import payloads

OUT = Path(__file__).parent / "fixtures" / "legacy_game.sql"


async def test_generate_legacy_fixture(harness, monkeypatch):
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    for msg in ("Je regarde autour.", "Je parle au barman.", "Je sors."):
        if msg == "Je sors.":
            # Record one deterministic successful Fate roll (all +1 dice, no pending roll).
            harness.llm._responses["mechanical"] = payloads.mechanical(
                requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
            monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
        await harness.chat(game_id, msg)
        await harness.drain()
    dump = subprocess.run(
        ["docker", "exec", "ci-pg", "pg_dump", "-U", "test", "-d", "ldvelh_test",
         "--data-only", "--inserts", "--exclude-table=schema_migrations"],
        check=True, capture_output=True, text=True,
    ).stdout
    # Keep only portable data statements: drop psql meta-commands (\\restrict, new in recent
    # pg_dump) and session SET / set_config lines, which asyncpg cannot run or which would
    # leak (search_path) into the pooled connection.
    kept = [ln for ln in dump.splitlines()
            if not ln.startswith(("\\", "SET ", "SELECT pg_catalog.set_config"))]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(f"-- legacy game {game_id}\n" + "\n".join(kept) + "\n", encoding="utf-8")
