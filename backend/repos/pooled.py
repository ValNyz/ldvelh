"""Reads through a pool, one connection per statement: a caller that awaits something
long between two reads (a model call) holds no connection meanwhile (#94)."""

from __future__ import annotations


class PooledReads:
    """The read methods of a connection (`fetch`, `fetchrow`, `fetchval`), each statement
    on a connection acquired for it and released at once. No transaction spans two
    statements: for reads that need no consistency between them."""

    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)
