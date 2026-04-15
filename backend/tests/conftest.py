"""
Configuration pytest et fixtures partagées
Importe les exemples depuis prompts/examples.py
"""

import json
import sys
from pathlib import Path

import pytest

# Ajouter le dossier backend au path pour les imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Configurer le logging pour les tests (moins verbeux)
import logging

logging.basicConfig(level=logging.WARNING)


# =============================================================================
# FIXTURES - Exemples importés depuis prompts/examples.py
# =============================================================================

from prompts.examples import (
    # World Generation
    WORLD_GENERATION_EXAMPLE,
    # Narration
    NARRATION_EXAMPLE_NEUTRAL,
    NARRATION_EXAMPLE_PNJ_UNAVAILABLE,
    NARRATION_EXAMPLE_DAY_TRANSITION,
    NARRATION_OUTPUT_TEMPLATE,
    # Extraction
    EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
    EXTRACTION_ENTITIES_EXAMPLE,
    EXTRACTION_FACTS_EXAMPLE,
    EXTRACTION_RELATIONS_EXAMPLE,
    EXTRACTION_ARCS_EXAMPLE,
    EXTRACTION_OBJECTS_EXAMPLE,
)


@pytest.fixture
def world_generation_example():
    """Exemple complet de génération de monde (parsed as dict)"""
    return json.loads(WORLD_GENERATION_EXAMPLE)


@pytest.fixture
def narration_examples():
    """Tous les exemples de narration"""
    return {
        "neutral": NARRATION_EXAMPLE_NEUTRAL,
        "pnj_unavailable": NARRATION_EXAMPLE_PNJ_UNAVAILABLE,
        "day_transition": NARRATION_EXAMPLE_DAY_TRANSITION,
        "template": NARRATION_OUTPUT_TEMPLATE,
    }


@pytest.fixture
def extraction_examples():
    """Tous les exemples d'extraction"""
    return {
        "protagonist_state": EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
        "entities": EXTRACTION_ENTITIES_EXAMPLE,
        "facts": EXTRACTION_FACTS_EXAMPLE,
        "relations": EXTRACTION_RELATIONS_EXAMPLE,
        "arcs": EXTRACTION_ARCS_EXAMPLE,
        "objects": EXTRACTION_OBJECTS_EXAMPLE,
        "full": {
            "cycle": 5,
            "time": "10h20",
            "current_location_ref": "Le Quart de Cycle",
            "facts": EXTRACTION_FACTS_EXAMPLE["facts"],
            "entities_created": EXTRACTION_ENTITIES_EXAMPLE["entities_created"],
            "entities_updated": EXTRACTION_ENTITIES_EXAMPLE["entities_updated"],
            "relations_created": EXTRACTION_RELATIONS_EXAMPLE["relations_created"],
            "relations_updated": EXTRACTION_RELATIONS_EXAMPLE["relations_updated"],
            "credit_transactions": EXTRACTION_PROTAGONIST_STATE_EXAMPLE[
                "credit_transactions"
            ],
            "inventory_changes": EXTRACTION_PROTAGONIST_STATE_EXAMPLE[
                "inventory_changes"
            ],
            "arcs_created": EXTRACTION_ARCS_EXAMPLE["arcs_created"],
            "arcs_resolved": EXTRACTION_ARCS_EXAMPLE["arcs_resolved"],
            "events_scheduled": EXTRACTION_ARCS_EXAMPLE["events_scheduled"],
            "objects_created": EXTRACTION_OBJECTS_EXAMPLE["objects_created"],
            "segment_summary": "Valentin commande un café au Quart de Cycle et discute brièvement avec Ossek.",
            "key_npcs_present": ["Ossek"],
        },
    }


# =============================================================================
# FIXTURES - Données de test réutilisables
# =============================================================================


@pytest.fixture
def sample_game_state():
    """État de jeu pour tests du state_normalizer"""
    return {
        "partie": {
            "nom": "Test Adventure",
            "cycle_actuel": 3,
            "date_jeu": "Mardi 2 janvier 2475",
            "heure": "14h30",
            "lieu_actuel": "Le Quart de Cycle",
            "pnjs_presents": ["Marie", "Jean"],
        },
        "valentin": {
            "energie": 3.5,
            "moral": 4.0,
            "sante": 5.0,
            "credits": 1200,
            "inventaire": [
                {"nom": "Communicateur", "quantite": 1},
            ],
        },
        "ia": {
            "nom": "Célimène",
            "personnalite": ["sarcastique", "loyale"],
            "quirk": "Fait des références obscures",
        },
    }


@pytest.fixture
def sample_narration_context():
    """Contexte de narration minimal pour tests"""
    from schema import (
        NarrationContext,
        LocationSummary,
        ProtagonistState,
    )

    return NarrationContext(
        current_cycle=1,
        current_date="Lundi 1er Janvier 2847",
        current_time="10h00",
        current_location=LocationSummary(
            name="Le Quart de Cycle",
            type="cafe",
            sector="Quai Central",
            atmosphere="calme",
        ),
        protagonist=ProtagonistState(
            name="Valentin",
            credits=1500,
            hobbies=["lecture"],
        ),
        organizations=[],
        all_npcs=[],
        player_input="Je regarde autour de moi",
        world_name="Escale Méridienne",
        world_atmosphere="industrielle",
    )


# =============================================================================
# MARKERS
# =============================================================================


def pytest_configure(config):
    """Ajoute des markers personnalisés"""
    config.addinivalue_line("markers", "slow: marque les tests lents")
    config.addinivalue_line(
        "markers", "integration: marque les tests d'intégration (nécessite BDD)"
    )


# =============================================================================
# INTEGRATION FIXTURES (require ldvelh_test database)
# =============================================================================

import pytest_asyncio

import os

# Set a test encryption key for API key storage tests (valid Fernet key)
if not os.getenv("ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://ldvelh:ldvelh@localhost:5432/ldvelh_test"
)

_TRUNCATE_SQL = "TRUNCATE games CASCADE; TRUNCATE users CASCADE; TRUNCATE genres CASCADE;"

# Parsed DSN components for admin connection (postgres maintenance DB)
_MAIN_DB_URL = os.getenv("DATABASE_URL", "postgresql://ldvelh:ldvelh@localhost:5432/ldvelh")
_TEST_DB_NAME = "ldvelh_test"


async def _ensure_test_db_exists():
    """Create ldvelh_test if it doesn't exist, copying schema from the main DB."""
    import asyncpg
    import asyncio
    import subprocess

    # Connect to the postgres maintenance database to check / create ldvelh_test
    admin_url = _MAIN_DB_URL.rsplit("/", 1)[0] + "/postgres"
    try:
        conn = await asyncpg.connect(admin_url)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to postgres admin DB at {admin_url!r}: {exc}"
        ) from exc

    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME
        )
        if not exists:
            # CREATE DATABASE cannot run inside a transaction block
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')

            # Dump schema from main DB and apply to test DB
            # Build pg_dump / psql connection args from the main DB URL
            # URL format: postgresql://user:password@host:port/dbname
            import urllib.parse
            parsed = urllib.parse.urlparse(_MAIN_DB_URL)
            env = os.environ.copy()
            env["PGPASSWORD"] = parsed.password or ""

            pg_dump_cmd = [
                "pg_dump",
                "--schema-only",
                f"--host={parsed.hostname}",
                f"--port={parsed.port or 5432}",
                f"--username={parsed.username}",
                parsed.path.lstrip("/"),
            ]
            parsed_test = urllib.parse.urlparse(TEST_DB_URL)
            psql_cmd = [
                "psql",
                f"--host={parsed_test.hostname}",
                f"--port={parsed_test.port or 5432}",
                f"--username={parsed_test.username}",
                _TEST_DB_NAME,
            ]

            dump = subprocess.run(pg_dump_cmd, capture_output=True, env=env)
            if dump.returncode != 0:
                raise RuntimeError(
                    f"pg_dump failed: {dump.stderr.decode()}"
                )
            restore = subprocess.run(
                psql_cmd, input=dump.stdout, capture_output=True, env=env
            )
            if restore.returncode != 0:
                raise RuntimeError(
                    f"psql schema restore failed: {restore.stderr.decode()}"
                )
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def test_pool():
    """Function-scoped asyncpg pool to the test database.

    Auto-creates ldvelh_test and copies schema from the main DB if needed.
    Uses min_size=1 to minimize connection creation overhead.
    Only TRUNCATEs at setup (not teardown) — next test will TRUNCATE anyway.
    Skips gracefully (pytest.skip) if the DB is unreachable.
    """
    import asyncpg
    import json
    import pytest

    try:
        await _ensure_test_db_exists()
    except Exception as exc:
        pytest.skip(f"Test DB not available: {exc}")
        return

    async def _init_conn(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    try:
        pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=5, init=_init_conn)
    except Exception as exc:
        pytest.skip(f"Cannot create test DB pool: {exc}")
        return

    async with pool.acquire() as conn:
        await conn.execute(_TRUNCATE_SQL)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def seeded_genres(test_pool):
    """Seed the 4 default genres into the test DB."""
    async with test_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM genres")
        if count == 0:
            for slug, label in [
                ("sci_fi", "Science-Fiction"),
                ("dark_fantasy", "Dark Fantasy"),
                ("cosmic_horror", "Horreur Cosmique"),
                ("cyberpunk", "Cyberpunk"),
            ]:
                await conn.execute(
                    "INSERT INTO genres (slug, label, is_preset) VALUES ($1, $2, true) ON CONFLICT DO NOTHING",
                    slug,
                    label,
                )


@pytest_asyncio.fixture
async def test_user(test_pool, monkeypatch) -> dict:
    """Create a test user and return {id, email, token}."""
    from services import auth_service

    # Mock email sending in tests (patch on auth_service where it's imported)
    async def _noop_send(*args, **kwargs):
        return True

    monkeypatch.setattr(auth_service, "send_verification_email", _noop_send)

    async with test_pool.acquire() as conn:
        result = await auth_service.register(conn, "test@example.com", "testpassword", "Test User")
    return {"id": result["id"], "email": result["email"], "token": result["token"]}


@pytest_asyncio.fixture
async def second_user(test_pool, monkeypatch) -> dict:
    """Create a second test user for access-denied tests."""
    from services import auth_service

    async def _noop_send(*args, **kwargs):
        return True

    monkeypatch.setattr(auth_service, "send_verification_email", _noop_send)

    async with test_pool.acquire() as conn:
        result = await auth_service.register(conn, "other@example.com", "otherpassword", "Other User")
    return {"id": result["id"], "email": result["email"], "token": result["token"]}


@pytest_asyncio.fixture
async def client(test_pool, monkeypatch):
    """httpx.AsyncClient with ASGI transport, using the test DB pool."""
    import httpx
    from main import app
    import main
    from services import auth_service

    monkeypatch.setattr(main, "db_pool", test_pool)

    # Mock email sending for all HTTP-based registration tests
    async def _noop_send(*args, **kwargs):
        return True

    monkeypatch.setattr(auth_service, "send_verification_email", _noop_send)

    # Reset rate limiter between tests
    from utils.rate_limit import auth_limiter
    auth_limiter._hits.clear()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
