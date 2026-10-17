"""User repository: stored preferences and API keys."""

import json
from uuid import UUID

from utils.crypto import decrypt_value


async def get_user_api_key(conn, user_id: UUID, provider: str) -> str | None:
    """Read the user's encrypted API key for a provider and decrypt it."""
    prefs_raw = await conn.fetchval("SELECT preferences FROM users WHERE id = $1", user_id)
    if not prefs_raw:
        return None
    prefs = prefs_raw if isinstance(prefs_raw, dict) else json.loads(prefs_raw)
    encrypted_key = prefs.get("api_keys", {}).get(provider)
    if not encrypted_key:
        return None
    return decrypt_value(encrypted_key)
