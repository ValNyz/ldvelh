"""
Latency test: measures resolver + extraction timing via the real API.
Creates a new world, plays 8 turns, measures each step.

Usage:
    cd backend
    python -m tests.benchmark.latency_test [--turns 8] [--provider wandb]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

import httpx
import asyncpg

logger = logging.getLogger(__name__)


async def consume_sse(response) -> dict:
    """Parse SSE stream, return game_state from done event."""
    game_state = None
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if data.get("type") == "done":
                game_state = data.get("state")
            elif data.get("type") == "error":
                logger.warning(f"SSE error: {data.get('error')}")
    return game_state


async def run_latency_test(num_turns: int = 8, provider: str = "wandb"):
    pool = await asyncpg.create_pool(
        os.getenv("TEST_DATABASE_URL", "postgresql://ldvelh:ldvelh@localhost:5432/ldvelh_test"),
        min_size=1, max_size=5,
        init=lambda c: c.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"),
    )

    from main import app
    import main
    main.db_pool = pool

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(300.0),
    ) as client:
        # Auth
        email = f"latency-{int(time.time())}@ldvelh.test"
        resp = await client.post("/api/auth/register", json={
            "email": email, "password": "testpwd", "password_confirm": "testpwd",
        })
        if resp.status_code == 409:
            resp = await client.post("/api/auth/login", json={
                "identifier": email, "password": "testpwd",
            })
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Store API key
        from utils.crypto import encrypt_value
        api_key = os.getenv("WANDB_API_KEY", "")
        prefs = {"api_keys": {provider: encrypt_value(api_key)}}
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE users SET preferences = $1::jsonb WHERE email = $2",
                prefs, email,
            )

        # Create game
        resp = await client.post("/api/games", json={"engine": "fate_core"}, headers=headers)
        game_id = resp.json()["gameId"]
        game_uuid = __import__("uuid").UUID(game_id)
        print(f"Game: {game_id}\n")

        # World gen
        print("Generating world...")
        t0 = time.perf_counter()
        async with client.stream("POST", "/api/chat", json={
            "message": "__INIT__", "gameId": game_id, "gameState": None,
            "provider": provider, "engine": "fate_core",
        }, headers=headers) as resp:
            game_state = await consume_sse(resp)
        print(f"World gen: {(time.perf_counter()-t0)*1000:.0f}ms\n")

        # Arrival
        print("Starting adventure...")
        t0 = time.perf_counter()
        async with client.stream("POST", "/api/chat", json={
            "message": "__ARRIVEE__", "gameId": game_id,
            "gameState": game_state, "provider": provider,
        }, headers=headers) as resp:
            game_state = await consume_sse(resp)
        print(f"Arrival: {(time.perf_counter()-t0)*1000:.0f}ms\n")

        # Play turns
        messages = [
            "Je regarde autour de moi et je cherche quelqu'un a qui parler.",
            "Je m'approche de cette personne et je lui demande son nom.",
            "Je lui pose des questions sur ce qu'elle fait sur la station.",
            "Je vais explorer le couloir principal de la station.",
            "Je m'arrete devant une vitrine et j'observe les objets exposes.",
            "Je retourne voir la personne que j'ai rencontree tout a l'heure.",
            "Je lui demande ce qu'elle pense de la vie sur cette station.",
            "Je la remercie et je pars explorer un autre secteur.",
        ][:num_turns]

        print(f"{'Turn':<6} {'Narr(ms)':<10} {'Resolver':<20} {'Extraction':<20} {'DB state':<25}")
        print("-" * 81)

        for i, msg in enumerate(messages):
            t_start = time.perf_counter()

            async with client.stream("POST", "/api/chat", json={
                "message": msg, "gameId": game_id,
                "gameState": game_state, "provider": provider,
            }, headers=headers) as resp:
                game_state = await consume_sse(resp)

            t_narr = (time.perf_counter() - t_start) * 1000

            # Wait for background tasks
            await asyncio.sleep(25)

            # Query results
            async with pool.acquire() as conn:
                ann = await conn.fetchrow(
                    """SELECT narrator_context FROM messages
                       WHERE game_id = $1 AND role = 'assistant'
                       ORDER BY sequence DESC LIMIT 1""",
                    game_uuid,
                )
                ann_data = ann["narrator_context"] if ann else None
                if isinstance(ann_data, str):
                    ann_data = json.loads(ann_data)
                ann_count = len(ann_data) if isinstance(ann_data, list) else 0

                chars = await conn.fetchval("SELECT COUNT(*) FROM characters WHERE game_id = $1", game_uuid)
                known = await conn.fetchval(
                    "SELECT COUNT(*) FROM characters WHERE game_id = $1 AND known_by_protagonist = true", game_uuid
                )
                facts = await conn.fetchval("SELECT COUNT(*) FROM facts WHERE game_id = $1", game_uuid)
                rels = await conn.fetchval("SELECT COUNT(*) FROM relations WHERE game_id = $1", game_uuid)
                ext_logs = await conn.fetchval("SELECT COUNT(*) FROM extraction_logs WHERE game_id = $1", game_uuid)

            resolver_col = f"{ann_count} spans" if ann_count > 0 else "no ann"
            ext_col = f"{ext_logs} logs"
            db_col = f"{chars}c({known}k) {facts}f {rels}r"

            print(f"{i+1:<6} {t_narr:<10.0f} {resolver_col:<20} {ext_col:<20} {db_col:<25}")

        # Summary
        print()
        async with pool.acquire() as conn:
            chars = await conn.fetchval("SELECT COUNT(*) FROM characters WHERE game_id = $1", game_uuid)
            known = await conn.fetchval(
                "SELECT COUNT(*) FROM characters WHERE game_id = $1 AND known_by_protagonist = true", game_uuid
            )
            locs = await conn.fetchval("SELECT COUNT(*) FROM locations WHERE game_id = $1", game_uuid)
            facts = await conn.fetchval("SELECT COUNT(*) FROM facts WHERE game_id = $1", game_uuid)
            rels = await conn.fetchval("SELECT COUNT(*) FROM relations WHERE game_id = $1", game_uuid)
            ann_msgs = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE game_id = $1 AND narrator_context IS NOT NULL", game_uuid
            )
            total_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE game_id = $1", game_uuid)

        print(f"Final: {chars} chars ({known} known), {locs} locs, {facts} facts, {rels} relations")
        print(f"Messages: {total_msgs} total, {ann_msgs} with annotations")

    await pool.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Resolver + extraction latency test")
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--provider", default="wandb")
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(message)s")
    logging.getLogger("services.extraction").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    asyncio.run(run_latency_test(num_turns=args.turns, provider=args.provider))
