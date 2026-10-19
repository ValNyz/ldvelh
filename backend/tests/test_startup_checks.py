"""Startup secrets validation: weak JWT secret or bad ENCRYPTION_KEY stops the backend (#39)."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from startup_checks import check_startup_config, startup_config_errors

STRONG = "q8V2m4Lx9TzR1cWn7KpB3yHs6JdF0aGe"  # 32 chars, random-looking
FERNET = Fernet.generate_key().decode()
PUBLISHED_CI_SECRET = "ci-test-secret-0123456789abcdef0123"
PUBLISHED_CI_KEY = "WkpQHs-KU7XuScnVGAxm35ucMGXCCGt1yLenNhtGqR0="


@pytest.mark.parametrize("debug", [False, True])
def test_strong_secret_with_key_passes(debug):
    assert startup_config_errors(STRONG, FERNET, debug=debug) == []


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("secret", [
    "",
    "short-but-random-9f3k",
    STRONG[:31],                                  # one char short
    "dev-secret-change-me-in-production!!",      # config.py former default
    "dev-secret-change-me",                      # old docker-compose default
    "change-me-to-a-random-64-char-string",      # .env.example placeholder
    PUBLISHED_CI_SECRET,                         # former CI / test-script value
    PUBLISHED_CI_SECRET.upper(),
    "x" * 20 + "CHANGE-ME" + "y" * 20,           # long but contains change-me
    "please-changeme-0123456789abcdef0123",
    " " * 40,                                    # whitespace only
    "  short-secret-9f3k  " + " " * 12,          # padded to 32 with blanks
    " " + STRONG,                                # stray whitespace around a good secret
    STRONG + "\n",
    "a" * 32,                                    # no variety
    "0" * 64,
    "abcdabcdabcdabcdabcdabcdabcdabcd",          # 4 distinct characters
])
def test_weak_jwt_secret_is_rejected_even_in_debug(secret, debug):
    errors = startup_config_errors(secret, FERNET, debug=debug)
    assert len(errors) == 1 and errors[0].startswith("JWT_SECRET")


@pytest.mark.parametrize("secret", [
    "56aa6e11deadfce51dfeaec6dacadd86",          # real `openssl rand -hex 16` output, 9 distinct chars
    "01234567012345670123456701234567",          # exactly 8 distinct chars
])
def test_legitimate_low_variety_secret_passes(secret):
    assert startup_config_errors(secret, FERNET, debug=False) == []


def test_missing_encryption_key_is_rejected_outside_debug():
    errors = startup_config_errors(STRONG, "", debug=False)
    assert len(errors) == 1 and errors[0].startswith("ENCRYPTION_KEY")


def test_missing_encryption_key_is_allowed_in_debug():
    assert startup_config_errors(STRONG, "", debug=True) == []


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("key", [
    "   ",                     # whitespace only
    "ab" * 32,                 # `openssl rand -hex 32`: 64 hex chars, not a Fernet key
    FERNET[:-4],               # truncated
    "not a key at all!",
    " " + FERNET,              # valid key with stray whitespace
    FERNET + "\n",
    PUBLISHED_CI_KEY,          # valid Fernet key, but published in the repo
])
def test_invalid_or_published_encryption_key_is_rejected(key, debug):
    errors = startup_config_errors(STRONG, key, debug=debug)
    assert len(errors) == 1 and errors[0].startswith("ENCRYPTION_KEY")


def test_all_problems_are_reported_together():
    assert len(startup_config_errors("short", "", debug=False)) == 2


def test_check_raises_with_every_message():
    settings = SimpleNamespace(jwt_secret="short", encryption_key="", debug=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET.*ENCRYPTION_KEY"):
        check_startup_config(settings)


def test_check_passes_on_valid_settings():
    check_startup_config(SimpleNamespace(jwt_secret=STRONG, encryption_key=FERNET, debug=False))


def test_config_has_no_usable_jwt_default(monkeypatch):
    """Without JWT_SECRET the setting is empty, which the validator rejects."""
    from config import Settings

    monkeypatch.delenv("JWT_SECRET", raising=False)
    settings = Settings(_env_file=None)
    assert settings.jwt_secret == ""
    assert startup_config_errors(settings.jwt_secret, FERNET, debug=True)


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


@pytest.mark.parametrize("env, name", [
    ({"WEB_CONCURRENCY": "2"}, "WEB_CONCURRENCY"),
    ({"UVICORN_WORKERS": "4"}, "UVICORN_WORKERS"),
    ({"WEB_CONCURRENCY": " 2 "}, "WEB_CONCURRENCY"),
])
def test_more_than_one_worker_is_refused(env, name):
    errors = startup_config_errors(STRONG, FERNET, debug=False, env=env)
    assert len(errors) == 1 and name in errors[0]


@pytest.mark.parametrize("env", [{}, {"WEB_CONCURRENCY": "1"}])
def test_one_worker_or_unset_passes(env):
    assert startup_config_errors(STRONG, FERNET, debug=False, env=env) == []


def test_an_invalid_language_pack_refuses_the_start(monkeypatch):
    from packs import loader
    from startup_checks import check_lang_packs, lang_pack_errors

    assert lang_pack_errors() == []

    def broken(lang):
        raise ValueError("a required key is missing")

    monkeypatch.setattr(loader, "load_lang", broken)
    with pytest.raises(RuntimeError, match="language pack"):
        check_lang_packs()


def test_a_pack_with_broken_yaml_refuses_the_start(monkeypatch):
    import yaml

    from packs import loader
    from startup_checks import lang_pack_errors

    def broken(lang):
        raise yaml.YAMLError("bad indentation")

    monkeypatch.setattr(loader, "load_lang", broken)
    assert any("language pack" in e for e in lang_pack_errors())


def test_a_misnamed_pack_file_refuses_the_start(monkeypatch):
    from packs import loader
    from startup_checks import check_lang_packs

    monkeypatch.setattr(loader, "misnamed_packs", lambda: ["lang/pt-BR.yaml"])
    with pytest.raises(RuntimeError, match="pt-BR"):
        check_lang_packs()


def test_a_default_language_without_pack_refuses_the_start(monkeypatch):
    import config
    from startup_checks import lang_pack_errors

    monkeypatch.setenv("IDENTITY_DEFAULT_LANGUAGE", "xx")
    config.get_identity_config.cache_clear()
    try:
        assert any("IDENTITY_DEFAULT_LANGUAGE='xx'" in e for e in lang_pack_errors())
    finally:
        monkeypatch.delenv("IDENTITY_DEFAULT_LANGUAGE")
        config.get_identity_config.cache_clear()


def test_the_escalation_alert_rate_must_exceed_the_target():
    from config import IdentityConfig

    with pytest.raises(ValueError, match="ESCALATION_ALERT_RATE"):
        IdentityConfig(escalation_target_rate=0.3, escalation_alert_rate=0.3)
    assert IdentityConfig(escalation_target_rate=0.2, escalation_alert_rate=0.25)
