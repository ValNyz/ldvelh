"""llm_models catalog fixture: an empty table for the test, seed rows restored afterwards."""

import pytest_asyncio


@pytest_asyncio.fixture
async def llm_table(test_pool):
    """Empty llm_models for the test, restoring the seed rows afterwards."""
    async with test_pool.acquire() as conn:
        saved = await conn.fetch("SELECT * FROM llm_models")
        await conn.execute("DELETE FROM llm_models")
    yield test_pool
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM llm_models")
        for r in saved:
            cols = list(r.keys())
            await conn.execute(
                f"INSERT INTO llm_models ({', '.join(cols)}) VALUES "
                f"({', '.join(f'${i + 1}' for i in range(len(cols)))})",
                *[r[c] for c in cols],
            )
