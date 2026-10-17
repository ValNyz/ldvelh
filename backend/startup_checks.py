"""Secrets validation run before the backend accepts traffic (fail-closed, #39)."""

MIN_JWT_SECRET_LENGTH = 32
# Values published in this repo at some point: anyone could sign tokens with them.
KNOWN_DEFAULT_SECRETS = frozenset({
    "dev-secret-change-me-in-production!!",
    "dev-secret-change-me",
    "change-me-to-a-random-64-char-string",
})
_PLACEHOLDER_MARKERS = ("change-me", "changeme")


def _jwt_secret_error(secret: str) -> str | None:
    lowered = secret.lower()
    if lowered in KNOWN_DEFAULT_SECRETS or any(m in lowered for m in _PLACEHOLDER_MARKERS):
        return "JWT_SECRET is a published default or placeholder: set a random secret."
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        return (f"JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters: "
                "set a random secret (e.g. `openssl rand -hex 32`).")
    return None


def startup_config_errors(jwt_secret: str, encryption_key: str, *, debug: bool) -> list[str]:
    """Every reason the backend must not start; empty when the configuration is acceptable.

    The JWT secret is checked whatever DEBUG says. ENCRYPTION_KEY (saved API keys)
    may only be missing in debug mode.
    """
    errors = []
    jwt_error = _jwt_secret_error(jwt_secret)
    if jwt_error:
        errors.append(jwt_error)
    if not encryption_key and not debug:
        errors.append("ENCRYPTION_KEY is not set: generate a Fernet key "
                      "(python -c \"from cryptography.fernet import Fernet; "
                      "print(Fernet.generate_key().decode())\").")
    return errors


def check_startup_config(settings) -> None:
    """Raise RuntimeError listing every configuration problem of `settings`."""
    errors = startup_config_errors(settings.jwt_secret, settings.encryption_key,
                                   debug=settings.debug)
    if errors:
        raise RuntimeError("Refusing to start: " + " ".join(errors))
