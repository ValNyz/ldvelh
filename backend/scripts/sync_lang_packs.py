"""Create `lang_packs` when it is missing and fill it from the YAML language packs (§4.12).

Run before `dbmate up` (backend/entrypoint.sh, scripts/test-backend.sh) so that the data
section of the identity migration can normalise names, and by the test fixture `test_pool`.
The table is the one the migration creates (same DDL, IF NOT EXISTS on both sides);
`packs.loader.sync_lang_packs` upserts every pack. Idempotent.

Usage (from backend/): DATABASE_URL=postgresql://… python -m scripts.sync_lang_packs
"""

from __future__ import annotations

import asyncio
import os
import sys

LANG_PACKS_DDL = """CREATE TABLE IF NOT EXISTS public.lang_packs (
    lang text PRIMARY KEY,
    version text NOT NULL,
    params jsonb NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
)"""


async def ensure_and_sync(conn) -> int:
    """Create lang_packs if needed, then upsert every language pack; the number written."""
    from packs.loader import sync_lang_packs

    await conn.execute(LANG_PACKS_DDL)
    return await sync_lang_packs(conn)


async def _main(database_url: str) -> int:
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        return await ensure_and_sync(conn)
    finally:
        await conn.close()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set")
    count = asyncio.run(_main(database_url))
    print(f"[LANG_PACKS] {count} language packs synchronised")


if __name__ == "__main__":
    main()
