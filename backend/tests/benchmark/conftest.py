"""
Benchmark suite configuration and shared fixtures.
"""

import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure backend is on path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "benchmark"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
GAME_DUMP_PATH = FIXTURES_DIR / "game_dump.json"


def pytest_addoption(parser):
    """Add benchmark-specific CLI options."""
    parser.addoption(
        "--regen-fixture",
        action="store_true",
        default=False,
        help="Regenerate benchmark fixture by playing a real game session",
    )
    parser.addoption(
        "--benchmark-depth",
        type=int,
        default=200,
        help="Number of turns to play when regenerating fixture (default: 200)",
    )
    parser.addoption(
        "--benchmark-provider",
        type=str,
        default="wandb",
        help="LLM provider for benchmark (default: wandb). Options: wandb, anthropic, nebius, etc.",
    )
    parser.addoption(
        "--benchmark-fixture",
        type=str,
        default=None,
        help="Path to game_dump.json fixture (default: tests/fixtures/benchmark/game_dump.json)",
    )


def pytest_configure(config):
    """Register benchmark markers."""
    config.addinivalue_line("markers", "benchmark: benchmark test (may require LLM API)")
    config.addinivalue_line("markers", "benchmark_llm: benchmark test requiring fresh LLM calls")


@pytest.fixture(scope="session")
def regen_fixture(request):
    """Whether to regenerate the game fixture."""
    return request.config.getoption("--regen-fixture")


@pytest.fixture(scope="session")
def benchmark_depth(request):
    """Number of turns for fixture generation."""
    return request.config.getoption("--benchmark-depth")


@pytest.fixture(scope="session")
def benchmark_provider(request):
    """LLM provider name for benchmark tests."""
    return request.config.getoption("--benchmark-provider")


@pytest.fixture(scope="session")
def game_dump(request):
    """Load the game dump fixture. Fails if it doesn't exist."""
    custom_path = request.config.getoption("--benchmark-fixture")
    path = Path(custom_path) if custom_path else GAME_DUMP_PATH
    if not path.exists():
        pytest.skip(
            f"Game dump not found at {path}. "
            "Run with --regen-fixture first to generate it."
        )
    with open(path) as f:
        data = json.load(f)
    print(f"\n[BENCHMARK] Loaded fixture: {path} ({len(data.get('turns', []))} turns)")
    return data



TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://ldvelh:ldvelh@localhost:5432/ldvelh_test"
)

async def _make_pool():
    """Create a fresh asyncpg pool bound to the current event loop."""
    import asyncpg

    async def _init_conn(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    return await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=5, init=_init_conn)


@pytest_asyncio.fixture
async def bench_pool():
    """Function-scoped asyncpg pool for benchmark tests."""
    pool = await _make_pool()
    yield pool
    await pool.close()


# Cache: stores the game info dict (game_id, etc.) — looked up once from DB
_game_info_cache: dict | None = None


async def get_game_pool_and_info(game_dump: dict) -> tuple:
    """Get a fresh pool + game info from the existing test DB.

    The game was created by game_player via the real API.
    No replay needed — the DB already has all the data.
    Returns (pool, info) where info has game_id, final_cycle, time, location.
    """
    global _game_info_cache

    pool = await _make_pool()

    if _game_info_cache is None:
        async with pool.acquire() as conn:
            # Find the game created by the benchmark player
            row = await conn.fetchrow(
                """SELECT g.id, g.current_cycle, g.current_time, g.name,
                          l.name as location_name
                   FROM games g
                   LEFT JOIN locations l ON g.current_location_id = l.id
                   WHERE g.user_id = (
                       SELECT id FROM users WHERE email = 'benchmark@ldvelh.test'
                   )
                   ORDER BY g.created_at DESC LIMIT 1"""
            )
            if not row:
                import pytest
                pytest.skip("No benchmark game found in test DB. Run game_player first.")

            _game_info_cache = {
                "game_id": row["id"],
                "final_cycle": row["current_cycle"] or 1,
                "time": str(row["current_time"]) if row["current_time"] else "14h00",
                "location": row["location_name"] or "",
            }

    return pool, _game_info_cache
