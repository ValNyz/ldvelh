"""
Game player: plays a real game session via the actual API to generate a game_dump.json fixture.
Requires a test DB and valid LLM API key.

Uses httpx.AsyncClient with ASGI transport to hit the real FastAPI endpoints —
same code path as production. This ensures extraction, deltas, mechanical steps,
and all other side effects run exactly as intended.

LLM-as-player: reads the last narrative + suggested actions and generates
a realistic player response each turn.

Usage:
    cd backend
    python -m tests.benchmark.game_player [--turns 200] [--engine fate_core] [--provider wandb]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Ensure backend is on path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from dotenv import load_dotenv
load_dotenv()

from services.llm_providers import get_provider
from .fixture_loader import get_db_snapshot

logger = logging.getLogger(__name__)

# First message only — after that, the LLM-as-player takes over
FIRST_MESSAGE = "Je regarde autour de moi et j'observe les alentours."

# Early milestones (generic — no NPC names, force an encounter)
EARLY_MILESTONES = [
    (0.01, "Je cherche quelqu'un a qui parler. Y a-t-il quelqu'un dans les environs?"),
    (0.02, "Je m'approche de cette personne et je lui demande son nom."),
    (0.03, "Je lui pose des questions sur ce qu'elle fait sur la station."),
    (0.04, "Je discute encore un peu avec cette personne. Qu'est-ce qu'elle pense de la station?"),
    (0.05, "Je la remercie et je lui dis au revoir."),
]

# Late recall templates — {npc_name} is replaced dynamically
LATE_RECALL_TEMPLATES = [
    (0.80, "Je repense a {npc_name} que j'ai rencontre en arrivant. Ou est-il maintenant?"),
    (0.82, "Je cherche {npc_name} dans la station pour le retrouver."),
    (0.85, "Je demande aux gens autour de moi s'ils ont vu {npc_name} recemment."),
    (0.90, "Je fais le bilan de tout ce que j'ai vecu sur la station depuis mon arrivee."),
]


class NPCTracker:
    """Track the first NPC encountered for the recall benchmark."""

    def __init__(self):
        self.tracked_npc: str | None = None
        self.met_at_turn: int | None = None
        self.capture_window = (1, 6)

    def on_turn(self, turn_idx: int, npcs_present: list[str]):
        if self.tracked_npc:
            return
        low, high = self.capture_window
        if low <= turn_idx < high and npcs_present:
            self.tracked_npc = npcs_present[0]
            self.met_at_turn = turn_idx
            logger.info(f"[GAME_PLAYER] Tracked NPC captured: '{self.tracked_npc}' at turn {turn_idx}")

    def get_milestone(self, turn_idx: int, num_turns: int) -> str | None:
        for fraction, message in EARLY_MILESTONES:
            if turn_idx == int(fraction * num_turns):
                return message
        if self.tracked_npc:
            for fraction, template in LATE_RECALL_TEMPLATES:
                if turn_idx == int(fraction * num_turns):
                    return template.format(npc_name=self.tracked_npc)
        return None

    def get_forbidden_name(self) -> str | None:
        return self.tracked_npc


# System prompt for the player LLM
PLAYER_SYSTEM_PROMPT = """\
Tu es un joueur enthousiaste d'un jeu de role narratif sur une station spatiale.
Tu joues le role du protagoniste. A chaque tour, tu recois le dernier texte du narrateur
et des actions suggerees.

Regles:
- Reponds en UNE SEULE phrase courte (max 20 mots) decrivant ton action.
- Varie tes actions: exploration, dialogue avec PNJ (utilise leurs NOMS), achat/vente,
  actions physiques, progression d'intrigues.
- Suis les pistes narratives: si un PNJ te parle, reponds-lui. Si un lieu est mentionne, vas-y.
- Prefere les actions suggerees ~50% du temps, improvise le reste.
- Ne repete JAMAIS la meme action deux fois de suite.
- Ecris a la premiere personne ("Je...").
- Reponds UNIQUEMENT avec ton action, rien d'autre."""

async def _generate_player_message(
    player_provider,
    last_narrative: str,
    suggested_actions: list[str] | None,
    last_player_message: str | None,
    forbidden_npc: str | None = None,
) -> str:
    """Use LLM to generate a realistic player response."""
    parts = []
    if last_narrative:
        text = last_narrative[-500:] if len(last_narrative) > 500 else last_narrative
        parts.append(f"Dernier texte du narrateur:\n{text}")

    if suggested_actions:
        actions_str = "\n".join(f"- {a}" for a in suggested_actions[:4])
        parts.append(f"\nActions suggerees:\n{actions_str}")

    if last_player_message:
        parts.append(f"\n(Ta derniere action etait: \"{last_player_message}\" — fais autre chose)")

    system = PLAYER_SYSTEM_PROMPT
    if forbidden_npc:
        system += (
            f"\n\nREGLE IMPORTANTE: Ne mentionne JAMAIS le personnage '{forbidden_npc}'. "
            f"Oublie-le completement. Explore d'autres lieux, parle a d'autres gens."
        )

    user_prompt = "\n".join(parts) + "\n\nTon action:"

    try:
        result = await player_provider.complete(
            system_prompt=system,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.9,
            max_tokens=100,
        )
        if result and result.content and result.content.strip():
            msg = result.content.strip().split("\n")[0].strip().strip('"').strip("'")
            if msg:
                return msg
    except Exception as e:
        logger.warning(f"[GAME_PLAYER] Player LLM failed: {e}")

    if suggested_actions:
        return suggested_actions[0]
    return "Je continue d'explorer les environs."


# =============================================================================
# SSE STREAM PARSER
# =============================================================================


async def _consume_sse_stream(response: httpx.Response) -> dict:
    """Parse an SSE stream from POST /chat and return aggregated result.

    Returns dict with:
        narrative_text: full narrative
        narration_output: parsed JSON (if available)
        game_state: from done event
        error: error message (if any)
        npcs_present: list of NPC names from narration
        suggested_actions: list of suggested actions
    """
    chunks = []
    done_data = None
    error_msg = None

    async for line in response.aiter_lines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue  # empty line or keepalive comment
        if line.startswith("data:"):
            raw = line[5:].strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            evt_type = data.get("type", "")

            if evt_type == "chunk":
                chunks.append(data.get("content", ""))
            elif evt_type == "done":
                done_data = data
            elif evt_type == "error":
                error_msg = data.get("error", "Unknown error")
                logger.warning(f"[GAME_PLAYER] SSE error: {error_msg}")

    narrative_text = "".join(chunks)

    # Extract game state from done event
    game_state = None
    display_text = None

    if done_data:
        display_text = done_data.get("displayText")
        state = done_data.get("state", {})
        game_state = state

    # Use displayText if available (it's the fully assembled narrative)
    if display_text:
        narrative_text = display_text

    return {
        "narrative_text": narrative_text,
        "game_state": game_state,
        "error": error_msg,
    }


# =============================================================================
# MAIN GAME PLAYER
# =============================================================================


async def play_game(
    pool,
    num_turns: int = 200,
    engine: str = "fate_core",
    provider_name: str = "wandb",
    api_key: str | None = None,
    snapshot_at: list[int] | None = None,
) -> dict:
    """Play a full game session via the real API and return the dump data.

    Uses httpx.AsyncClient with ASGI transport to call the actual FastAPI app.
    This ensures the full code path runs: context building, mechanical steps,
    narration, deltas, extraction — exactly like production.
    """
    import asyncpg
    from main import app
    import main

    # Inject the test pool into the app
    main.db_pool = pool

    if snapshot_at is None:
        snapshot_at = [50, 100, 150, num_turns]

    # Player LLM provider
    player_provider = get_provider(provider_name, api_key=api_key)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(120.0),
    ) as client:
        # 1. Register user and get token
        reg_resp = await client.post("/api/auth/register", json={
            "email": "benchmark@ldvelh.test",
            "password": "benchmarkpassword",
            "password_confirm": "benchmarkpassword",
            "display_name": "Benchmark Player",
        })
        if reg_resp.status_code == 409:
            # User exists, login instead
            login_resp = await client.post("/api/auth/login", json={
                "identifier": "benchmark@ldvelh.test",
                "password": "benchmarkpassword",
            })
            login_resp.raise_for_status()
            token = login_resp.json()["token"]
        else:
            reg_resp.raise_for_status()
            token = reg_resp.json()["token"]

        headers = {"Authorization": f"Bearer {token}"}

        # 1b. Store API key in user preferences so the API can use it
        wandb_key = api_key or os.getenv("WANDB_API_KEY", "")
        if wandb_key:
            from utils.crypto import encrypt_value
            encrypted = encrypt_value(wandb_key)
            prefs = {"api_keys": {provider_name: encrypted}}
            async with pool.acquire() as conn:
                # Pool has jsonb codec, so pass dict directly
                await conn.execute(
                    "UPDATE users SET preferences = $1::jsonb WHERE email = 'benchmark@ldvelh.test'",
                    prefs,
                )
            logger.info(f"[GAME_PLAYER] Stored {provider_name} API key in user preferences")

        # 2. Create game
        create_resp = await client.post(
            "/api/games",
            json={"engine": engine},
            headers=headers,
        )
        create_resp.raise_for_status()
        game_id = create_resp.json()["gameId"]

        logger.info(f"[GAME_PLAYER] Game {game_id} created with engine={engine}")
        logger.info(f"[GAME_PLAYER] Provider: {provider_name}")

        # 3. World generation (__INIT__)
        logger.info("[GAME_PLAYER] Starting world generation...")
        async with client.stream(
            "POST", "/api/chat",
            json={
                "message": "__INIT__",
                "gameId": game_id,
                "gameState": None,
                "provider": provider_name,
                "engine": engine,
            },
            headers=headers,
        ) as init_resp:
            init_result = await _consume_sse_stream(init_resp)

        if init_result["error"]:
            raise RuntimeError(f"World generation failed: {init_result['error']}")
        logger.info("[GAME_PLAYER] World generation complete")

        # Get world gen data from DB for the dump
        game_uuid = __import__("uuid").UUID(game_id)
        async with pool.acquire() as conn:
            game_row = await conn.fetchrow(
                "SELECT world_name, world_description, world_atmosphere FROM games WHERE id = $1",
                game_uuid,
            )
            world_characters = await conn.fetch(
                "SELECT name, occupation, species FROM characters WHERE game_id = $1",
                game_uuid,
            )
            world_locations = await conn.fetch(
                "SELECT name, location_type, sector FROM locations WHERE game_id = $1",
                game_uuid,
            )

        # 4. Start adventure (__ARRIVEE__)
        logger.info("[GAME_PLAYER] Starting adventure...")
        async with client.stream(
            "POST", "/api/chat",
            json={
                "message": "__ARRIVEE__",
                "gameId": game_id,
                "gameState": init_result.get("game_state"),
                "provider": provider_name,
            },
            headers=headers,
        ) as arrival_resp:
            arrival_result = await _consume_sse_stream(arrival_resp)

        if arrival_result["error"]:
            raise RuntimeError(f"Adventure start failed: {arrival_result['error']}")
        logger.info("[GAME_PLAYER] Adventure started")

        # 5. Play turns
        turns = []
        npc_tracker = NPCTracker()
        start_time = time.perf_counter()
        last_narrative = arrival_result["narrative_text"]
        last_player_message = None
        game_state = arrival_result.get("game_state")
        snapshots = {}

        for turn_idx in range(num_turns):
            # Choose message: milestone > LLM-as-player > seed
            milestone = npc_tracker.get_milestone(turn_idx, num_turns)
            if turn_idx == 0:
                user_message = FIRST_MESSAGE
            elif milestone:
                user_message = milestone
                logger.info(f"[GAME_PLAYER] MILESTONE at turn {turn_idx}: \"{milestone[:60]}\"")
            else:
                forbidden = npc_tracker.get_forbidden_name() if npc_tracker.tracked_npc else None
                user_message = await _generate_player_message(
                    player_provider, last_narrative, None,
                    last_player_message, forbidden_npc=forbidden,
                )

            turn_start = time.perf_counter()

            try:
                # Call POST /chat — the real API, with streaming
                async with client.stream(
                    "POST", "/api/chat",
                    json={
                        "message": user_message,
                        "gameId": game_id,
                        "gameState": game_state,
                        "provider": provider_name,
                    },
                    headers=headers,
                ) as chat_resp:
                    result = await _consume_sse_stream(chat_resp)

                if result["error"]:
                    logger.warning(f"[GAME_PLAYER] Error at turn {turn_idx}: {result['error']}")
                    turns.append({
                        "turn_index": turn_idx,
                        "user_message": user_message,
                        "narrative_text": None,
                        "error": result["error"],
                    })
                    continue

                # Update state
                if result.get("game_state"):
                    game_state = result["game_state"]
                last_narrative = result["narrative_text"]
                last_player_message = user_message

                # Track NPCs from DB (characters marked known this turn)
                async with pool.acquire() as conn:
                    known_chars = await conn.fetch(
                        "SELECT name FROM characters WHERE game_id = $1 AND known_by_protagonist = true",
                        game_uuid,
                    )
                known_names = [r["name"] for r in known_chars]
                npc_tracker.on_turn(turn_idx, known_names)

                # Record turn
                turn_data = {
                    "turn_index": turn_idx,
                    "user_message": user_message,
                    "narrative_text": result["narrative_text"],
                }
                turns.append(turn_data)

                turn_elapsed = time.perf_counter() - turn_start
                total_elapsed = time.perf_counter() - start_time
                done = turn_idx + 1
                avg_per_turn = total_elapsed / done
                eta = avg_per_turn * (num_turns - done)
                eta_min, eta_sec = divmod(int(eta), 60)
                pct = 100 * done / num_turns
                errors = sum(1 for t in turns if t.get("error"))

                logger.info(
                    f"[GAME_PLAYER] Turn {done}/{num_turns} ({pct:.0f}%) "
                    f"| {turn_elapsed:.1f}s | ETA {eta_min}m{eta_sec:02d}s "
                    f"| errors: {errors} "
                    f"| \"{user_message[:50]}\""
                )

                # Take snapshot if at checkpoint
                if (turn_idx + 1) in snapshot_at:
                    snapshot = await get_db_snapshot(pool, game_uuid)
                    snapshots[f"turn_{turn_idx + 1}"] = _serialize_snapshot(snapshot)
                    logger.info(f"[GAME_PLAYER] Snapshot at turn {turn_idx + 1}")

            except Exception as e:
                logger.error(f"[GAME_PLAYER] Error at turn {turn_idx}: {e}", exc_info=True)
                turns.append({
                    "turn_index": turn_idx,
                    "user_message": user_message,
                    "narration_output": None,
                    "error": str(e),
                })

    total_elapsed = time.perf_counter() - start_time

    # Final snapshot
    final_snapshot = await get_db_snapshot(pool, game_uuid)
    snapshots["final"] = _serialize_snapshot(final_snapshot)

    dump = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_turns": len(turns),
            "engine": engine,
            "provider": provider_name,
            "total_time_seconds": round(total_elapsed, 1),
            "errors": sum(1 for t in turns if t.get("error")),
            "tracked_npc": npc_tracker.tracked_npc,
            "tracked_npc_met_at_turn": npc_tracker.met_at_turn,
        },
        "world_gen": {
            "world_name": game_row["world_name"] if game_row else None,
            "world_description": game_row["world_description"] if game_row else None,
            "world_atmosphere": game_row["world_atmosphere"] if game_row else None,
            "characters": [dict(r) for r in world_characters],
            "locations": [dict(r) for r in world_locations],
        },
        "turns": turns,
        "snapshots": snapshots,
    }

    return dump


def _serialize_snapshot(snapshot: dict) -> dict:
    """Make snapshot JSON-serializable (convert UUIDs, dates, etc.)."""
    import uuid
    from datetime import date, datetime as dt, time as dt_time

    def _convert(obj):
        if isinstance(obj, (uuid.UUID,)):
            return str(obj)
        if isinstance(obj, (date, dt, dt_time)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(item) for item in obj]
        return obj

    return _convert(snapshot)


async def generate_and_save(
    num_turns: int = 200,
    engine: str = "fate_core",
    provider_name: str = "wandb",
    output_path: Path | None = None,
) -> Path:
    """Generate a game dump and save to file.

    Standalone entry point — creates its own DB pool.
    """
    import asyncpg

    db_url = os.getenv(
        "TEST_DATABASE_URL", "postgresql://ldvelh:ldvelh@localhost:5432/ldvelh_test"
    )

    async def _init_conn(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5, init=_init_conn)

    try:
        dump = await play_game(pool, num_turns=num_turns, engine=engine, provider_name=provider_name)
    finally:
        await pool.close()

    if output_path is None:
        output_path = Path(__file__).parent.parent / "fixtures" / "benchmark" / "game_dump.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(dump, f, indent=2, ensure_ascii=False)

    logger.info(f"[GAME_PLAYER] Saved game dump to {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate LDVELH benchmark fixture")
    parser.add_argument("--turns", type=int, default=200, help="Number of turns to play")
    parser.add_argument("--engine", default="fate_core", help="Game engine to use")
    parser.add_argument("--provider", default="wandb", help="LLM provider (default: wandb)")
    parser.add_argument("--output", type=str, default=None, help="Output path for game_dump.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose: all backend logs (DEBUG)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet: errors + progress only")
    parser.add_argument(
        "--log-level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set backend log level explicitly (overrides -v/-q)",
    )
    args = parser.parse_args()

    if args.log_level:
        level = getattr(logging, args.log_level)
        logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    elif args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    elif args.quiet:
        logging.basicConfig(level=logging.WARNING, format="%(message)s")
        logging.getLogger(__name__).setLevel(logging.INFO)
    else:
        # Default: backend at INFO (see [CHAT], [EXTRACTION], [SSE] logs), suppress httpx noise
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    output = Path(args.output) if args.output else None
    asyncio.run(generate_and_save(
        num_turns=args.turns, engine=args.engine,
        provider_name=args.provider, output_path=output,
    ))
