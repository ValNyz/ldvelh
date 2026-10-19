"""Overhead of the zz_journal_* triggers on commit-shaped transactions (#105).

    python -m tests.benchmark.journal_overhead [--rounds 50]

runs against TEST_DATABASE_URL. Each round is one transaction shaped like a narration
commit, timed in three variants: journaled (under a unit of work), no_turn (triggers
fire but find no turn), disabled (journal triggers off on the touched tables).
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from uuid import UUID

import asyncpg

from repos import turns
from repos.uow import uow

# Tables the commit shape writes and that carry the journal triggers.
JOURNALED_TABLES = (
    "character_fate",
    "games",
    "protagonists",
    "locations",
    "mechanic_rolls",
)


async def _commit_shaped_writes(
    conn, game_id: UUID, conversation_id: UUID, n: int
) -> None:
    await conn.execute(
        "UPDATE character_fate SET fate_points = $2 WHERE game_id = $1", game_id, n % 5
    )
    await conn.execute(
        'UPDATE games SET "current_time" = $2 WHERE id = $1',
        game_id,
        f"{n % 24:02d}:{n % 60:02d}",
    )
    await conn.fetch("SELECT * FROM credit_transaction($1, -1, 1, 'bench')", game_id)
    stub = await conn.fetchval(
        "INSERT INTO locations (game_id, name) VALUES ($1, $2) RETURNING id",
        game_id,
        f"stub-{n}",
    )
    await conn.execute("DELETE FROM locations WHERE id = $1", stub)
    await conn.execute(
        """INSERT INTO mechanic_rolls (game_id, engine, roll_details, outcome)
        VALUES ($1, 'fate_core', '{}'::jsonb, 'success')""",
        game_id,
    )
    for role in ("user", "assistant"):
        await conn.execute(
            """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
            VALUES ($1, $2, $3, 'bench', $4)""",
            game_id,
            conversation_id,
            role,
            n * 2 + (role == "assistant"),
        )


async def _timed(conn, fn) -> float:
    start = time.perf_counter()
    await fn()
    return (time.perf_counter() - start) * 1000


async def _ensure_rows(conn, game_id: UUID) -> UUID:
    """Make sure the game has a Fate character, a protagonist and a conversation."""
    if not await conn.fetchval(
        "SELECT 1 FROM character_fate WHERE game_id = $1", game_id
    ):
        await conn.execute("INSERT INTO character_fate (game_id) VALUES ($1)", game_id)
    if not await conn.fetchval(
        "SELECT 1 FROM protagonists WHERE game_id = $1", game_id
    ):
        await conn.execute(
            "INSERT INTO protagonists (game_id, name) VALUES ($1, 'Bench')", game_id
        )
    await conn.execute(
        "UPDATE protagonists SET credits = 1000000 WHERE game_id = $1", game_id
    )
    conversation_id = await conn.fetchval(
        "SELECT id FROM conversations WHERE game_id = $1 LIMIT 1", game_id
    )
    if not conversation_id:
        conversation_id = await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
            game_id,
        )
    return conversation_id


async def _set_journal(conn, enabled: bool) -> None:
    action = "ENABLE" if enabled else "DISABLE"
    for table in JOURNALED_TABLES:
        await conn.execute(f"ALTER TABLE {table} {action} TRIGGER zz_journal_id")
        await conn.execute(f"ALTER TABLE {table} {action} TRIGGER zz_journal_u")


async def measure(pool, game_id: UUID, *, rounds: int) -> dict:
    """Median ms of one commit-shaped transaction per variant, interleaved round by round."""
    times: dict[str, list[float]] = {"journaled": [], "no_turn": [], "disabled": []}
    async with pool.acquire() as conn:
        conversation_id = await _ensure_rows(conn, game_id)
        turn_id = await turns.open_turn(conn, game_id)
        base = await conn.fetchval(
            "SELECT coalesce(max(sequence), 0) + 1 FROM messages"
        )
        counter = base

        async def run(variant: str) -> None:
            nonlocal counter
            counter += 1
            n = counter

            async def body():
                if variant == "journaled":
                    async with uow(conn, turn_id):
                        await _commit_shaped_writes(conn, game_id, conversation_id, n)
                else:
                    async with conn.transaction():
                        await _commit_shaped_writes(conn, game_id, conversation_id, n)

            times[variant].append(await _timed(conn, body))

        for _ in range(rounds):
            await run("journaled")
            await run("no_turn")
            await _set_journal(conn, False)
            try:
                await run("disabled")
            finally:
                await _set_journal(conn, True)

        journal_bytes = await conn.fetchval(
            "SELECT coalesce(sum(pg_column_size(w.*)), 0) FROM world_changes w WHERE turn_id = $1",
            turn_id,
        )

    medians = {name: statistics.median(values) for name, values in times.items()}
    return {
        "rounds": rounds,
        "journaled_ms": medians["journaled"],
        "no_turn_ms": medians["no_turn"],
        "disabled_ms": medians["disabled"],
        "overhead": medians["journaled"] / medians["disabled"] - 1,
        "journal_bytes_per_round": journal_bytes / rounds,
    }


async def _bench_game(conn) -> UUID:
    user_id = await conn.fetchval(
        "INSERT INTO users (email, password_hash) VALUES ($1, 'x') RETURNING id",
        f"bench-{time.time_ns()}@example.com",
    )
    return await conn.fetchval(
        "INSERT INTO games (user_id, engine) VALUES ($1, 'fate_core') RETURNING id",
        user_id,
    )


async def _main(rounds: int) -> None:
    async def init(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], init=init)
    try:
        async with pool.acquire() as conn:
            game_id = await _bench_game(conn)
        result = await measure(pool, game_id, rounds=rounds)
    finally:
        await pool.close()
    for key, value in result.items():
        print(f"{key}: {value:.3f}" if isinstance(value, float) else f"{key}: {value}")
    print(f"overhead: {result['overhead'] * 100:.1f} %")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=50)
    asyncio.run(_main(parser.parse_args().rounds))
