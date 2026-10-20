"""Connection setup shared by every asyncpg pool of the app and its scripts."""

import json


async def init_connection(conn) -> None:
    """jsonb columns read and written as Python objects."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
