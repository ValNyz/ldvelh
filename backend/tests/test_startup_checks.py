"""Startup secrets validation: weak JWT secret or missing ENCRYPTION_KEY stops the backend (#39)."""

from types import SimpleNamespace

import pytest

from startup_checks import check_startup_config, startup_config_errors

STRONG = "q8V2m4Lx9TzR1cWn7KpB3yHs6JdF0aGe"  # 32 chars, random-looking
FERNET = "WkpQHs-KU7XuScnVGAxm35ucMGXCCGt1yLenNhtGqR0="


@pytest.mark.parametrize("debug", [False, True])
def test_strong_secret_with_key_passes(debug):
    assert startup_config_errors(STRONG, FERNET, debug=debug) == []


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("secret", [
    "",
    "short-but-random-9f3k",
    STRONG[:31],                                  # one char short
    "dev-secret-change-me-in-production!!",      # config.py default
    "dev-secret-change-me",                      # old docker-compose default
    "change-me-to-a-random-64-char-string",      # .env.example placeholder
    "x" * 20 + "CHANGE-ME" + "y" * 20,           # long but contains change-me
    "please-changeme-0123456789abcdef0123",
])
def test_weak_jwt_secret_is_rejected_even_in_debug(secret, debug):
    errors = startup_config_errors(secret, FERNET, debug=debug)
    assert len(errors) == 1 and errors[0].startswith("JWT_SECRET")


def test_ci_secret_is_accepted():
    """scripts/test-backend.sh and ci.yml use this value: it must satisfy the validator."""
    assert startup_config_errors("ci-test-secret-0123456789abcdef0123", FERNET, debug=True) == []


def test_missing_encryption_key_is_rejected_outside_debug():
    errors = startup_config_errors(STRONG, "", debug=False)
    assert len(errors) == 1 and errors[0].startswith("ENCRYPTION_KEY")


def test_missing_encryption_key_is_allowed_in_debug():
    assert startup_config_errors(STRONG, "", debug=True) == []


def test_all_problems_are_reported_together():
    assert len(startup_config_errors("short", "", debug=False)) == 2


def test_check_raises_with_every_message():
    settings = SimpleNamespace(jwt_secret="short", encryption_key="", debug=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET.*ENCRYPTION_KEY"):
        check_startup_config(settings)


def test_check_passes_on_valid_settings():
    check_startup_config(SimpleNamespace(jwt_secret=STRONG, encryption_key=FERNET, debug=False))


@pytest.mark.asyncio
async def test_lifespan_refuses_to_start_before_touching_the_db(monkeypatch):
    import main

    weak = SimpleNamespace(jwt_secret="dev-secret-change-me", encryption_key=FERNET, debug=True)
    monkeypatch.setattr(main, "get_settings", lambda: weak)

    async def _no_pool(*args, **kwargs):
        raise AssertionError("the pool must not be created with a weak secret")

    monkeypatch.setattr(main.asyncpg, "create_pool", _no_pool)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        async with main.lifespan(main.app):
            pass
