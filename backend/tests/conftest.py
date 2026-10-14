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
# Keep legacy top-level imports (e.g. `from helpers import ...`) working now that tests/ is a package
sys.path.insert(0, str(Path(__file__).parent))

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

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def assert_safe_test_db_url(url: str) -> None:
    """Refuse to touch any database whose name does not end with '_test'."""
    db_name = urlparse(url).path.lstrip("/")
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to use database '{db_name}': test DB name must end with '_test'"
        )


_DBMATE_DONE = False

_TRUNCATE_SQL = "TRUNCATE games CASCADE; TRUNCATE users CASCADE; TRUNCATE genres CASCADE;"



def _dbmate_url(url: str) -> str:
    """Return the URL dbmate should use: same DB, but with sslmode=disable if unset.

    dbmate >=2.33 defaults to SSL when sslmode is absent, and the test DB (local or
    the CI Postgres service) does not serve TLS, so it fails with
    "SSL is not enabled on the server". Existing query params and an explicit
    sslmode are preserved. asyncpg keeps using the original URL.
    """
    parts = urlparse(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key == "sslmode" for key, _ in query):
        return url
    query.append(("sslmode", "disable"))
    return urlunparse(parts._replace(query=urlencode(query)))


def _try_dbmate_setup():
    """Migrate the test DB with dbmate once per session (local dev only).

    In CI the workflow already migrates the DB; without dbmate on PATH this is a no-op.
    """
    import shutil
    import subprocess

    global _DBMATE_DONE
    if _DBMATE_DONE or not shutil.which("dbmate"):
        return
    _DBMATE_DONE = True

    migrations_dir = str(Path(__file__).parent.parent.parent / "db" / "migrations")
    env = os.environ.copy()
    # dbmate-only URL; TEST_DB_URL itself stays unchanged for asyncpg.
    env["DATABASE_URL"] = _dbmate_url(TEST_DB_URL)
    result = subprocess.run(
        ["dbmate", "--migrations-dir", migrations_dir, "--no-dump-schema", "up"],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0 and _require_test_db():
        import pytest

        pytest.fail(
            f"dbmate up failed (rc={result.returncode}) and REQUIRE_TEST_DB=1:\n{result.stderr}",
            pytrace=False,
        )


def _require_test_db() -> bool:
    """True when a missing/broken test DB must fail the run instead of skipping (CI)."""
    return os.environ.get("REQUIRE_TEST_DB") == "1"


def _db_unavailable(reason: str) -> None:
    """Skip locally, but fail when REQUIRE_TEST_DB=1 so CI cannot go green without a DB."""
    import pytest

    if _require_test_db():
        pytest.fail(f"Test DB required (REQUIRE_TEST_DB=1) but unavailable: {reason}", pytrace=False)
    pytest.skip(f"Test DB not available: {reason}")


@pytest_asyncio.fixture
async def test_pool():
    """Function-scoped asyncpg pool to the test database.

    Tries dbmate setup locally, then connects. Skips if DB unreachable.
    """
    assert_safe_test_db_url(TEST_DB_URL)
    import asyncpg
    import json
    import pytest

    _try_dbmate_setup()

    async def _init_conn(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    try:
        pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=5, init=_init_conn)
        async with pool.acquire() as conn:
            await conn.execute(_TRUNCATE_SQL)
    except Exception as exc:
        _db_unavailable(str(exc))
        return

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
                    """INSERT INTO genres (slug, label, is_preset, tone_style, friction_flavor)
                       VALUES ($1, $2, true, 'neutral', 'standard')
                       ON CONFLICT DO NOTHING""",
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


def pytest_collection_modifyitems(config, items):
    """Tag every test that (transitively) uses test_pool with requires_db."""
    for item in items:
        if "test_pool" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.requires_db)
