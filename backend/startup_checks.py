"""Secrets validation run before the backend accepts traffic (fail-closed, #39)."""

import binascii
import os
from collections.abc import Mapping

from cryptography.fernet import Fernet

MIN_JWT_SECRET_LENGTH = 32
MIN_JWT_SECRET_DISTINCT_CHARS = 8  # rejects "a"*32; a random 32-hex secret can have only ~9
# Values published in this repo at some point: anyone could sign tokens with them.
KNOWN_DEFAULT_SECRETS = frozenset({
    "dev-secret-change-me-in-production!!",
    "dev-secret-change-me",
    "change-me-to-a-random-64-char-string",
    "ci-test-secret-0123456789abcdef0123",
})
# Fernet keys published in this repo (former CI / test-script value).
KNOWN_ENCRYPTION_KEYS = frozenset({
    "WkpQHs-KU7XuScnVGAxm35ucMGXCCGt1yLenNhtGqR0=",
})
_PLACEHOLDER_MARKERS = ("change-me", "changeme")
_GENERATE_JWT = "set a random secret (e.g. `openssl rand -hex 32`)."
_GENERATE_KEY = ("generate one with python -c \"from cryptography.fernet import Fernet; "
                 "print(Fernet.generate_key().decode())\" (local dev: scripts/dev-setup.sh).")


def _jwt_secret_error(secret: str) -> str | None:
    stripped = secret.strip()
    lowered = stripped.lower()
    if lowered in KNOWN_DEFAULT_SECRETS or any(m in lowered for m in _PLACEHOLDER_MARKERS):
        return "JWT_SECRET is a published default or placeholder: " + _GENERATE_JWT
    if stripped != secret:
        return "JWT_SECRET has leading or trailing whitespace: " + _GENERATE_JWT
    if len(stripped) < MIN_JWT_SECRET_LENGTH:
        return f"JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters: " + _GENERATE_JWT
    if len(set(stripped)) < MIN_JWT_SECRET_DISTINCT_CHARS:
        return (f"JWT_SECRET uses fewer than {MIN_JWT_SECRET_DISTINCT_CHARS} distinct characters: "
                + _GENERATE_JWT)
    return None


def _encryption_key_error(key: str, debug: bool) -> str | None:
    if not key:
        return None if debug else "ENCRYPTION_KEY is not set: " + _GENERATE_KEY
    if key.strip() in KNOWN_ENCRYPTION_KEYS:
        return "ENCRYPTION_KEY is a key published in the repository: " + _GENERATE_KEY
    if key.strip() != key:
        return "ENCRYPTION_KEY has leading or trailing whitespace: " + _GENERATE_KEY
    try:
        Fernet(key.encode())
    except (ValueError, binascii.Error):
        return "ENCRYPTION_KEY is not a valid Fernet key: " + _GENERATE_KEY
    return None


_WORKER_COUNT_VARIABLES = ("WEB_CONCURRENCY", "UVICORN_WORKERS")


def worker_count_error(env: Mapping[str, str]) -> str | None:
    """Refuse a multi-worker start: game locks and the task supervisor are per process."""
    for name in _WORKER_COUNT_VARIABLES:
        value = env.get(name)
        if value is not None and value.strip() != "1":
            return (f"{name}={value}: LDVELH runs a single uvicorn worker (in-process game "
                    "locks and task supervisor); unset it or set it to 1.")
    return None


def startup_config_errors(jwt_secret: str, encryption_key: str, *, debug: bool,
                          env: Mapping[str, str] | None = None) -> list[str]:
    """Every reason the backend must not start; empty when the configuration is acceptable.

    The JWT secret is checked whatever DEBUG says. ENCRYPTION_KEY (saved API keys) may only
    be missing in debug mode; when set, it must be a valid, unpublished Fernet key. `env`
    (default `os.environ`) is checked for a multi-worker setting.
    """
    errors = [_jwt_secret_error(jwt_secret), _encryption_key_error(encryption_key, debug),
              worker_count_error(os.environ if env is None else env)]
    return [error for error in errors if error]


def check_startup_config(settings) -> None:
    """Raise RuntimeError listing every configuration problem of `settings`."""
    errors = startup_config_errors(settings.jwt_secret, settings.encryption_key,
                                   debug=settings.debug)
    if errors:
        raise RuntimeError("Refusing to start: " + " ".join(errors))


def lang_pack_errors() -> list[str]:
    """Every language or genre pack that does not load, every pack file with an invalid name,
    and a default language without pack."""
    import yaml

    from config import get_identity_config
    from packs.loader import (
        PackNotFound,
        available_genres,
        available_langs,
        load_genre,
        load_lang,
        misnamed_packs,
    )

    # pydantic's ValidationError is a ValueError.
    broken = (ValueError, yaml.YAMLError, PackNotFound)
    errors = [f"pack file {name} has an invalid name" for name in misnamed_packs()]
    for lang in available_langs():
        try:
            load_lang(lang)
        except broken as exc:
            errors.append(f"language pack {lang!r} is invalid: {exc}")
    for slug in available_genres():
        try:
            load_genre(slug)
        except broken as exc:
            errors.append(f"genre pack {slug!r} is invalid: {exc}")
    default = get_identity_config().default_language
    if default not in available_langs():
        errors.append(f"IDENTITY_DEFAULT_LANGUAGE={default!r} has no language pack")
    return errors


def check_lang_packs() -> None:
    """Raise RuntimeError when a pack is invalid: the backend does not start without them."""
    errors = lang_pack_errors()
    if errors:
        raise RuntimeError("Refusing to start: " + " ".join(errors))


async def sync_language_packs(pool) -> int:
    """Copy the language packs into lang_packs, read by ldvelh_norm (spec §4.12)."""
    from packs.loader import sync_lang_packs

    async with pool.acquire() as conn:
        return await sync_lang_packs(conn)
