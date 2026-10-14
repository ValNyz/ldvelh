"""Drive POST /chat end-to-end through ASGI and summarize what happened."""

import asyncio
import json


class ChatHarness:
    def __init__(self, client, pool, token: str, llm):
        self.client = client
        self.pool = pool
        self.headers = {"Authorization": f"Bearer {token}"}
        self.llm = llm

    async def create_game(self, engine: str = "none") -> str:
        r = await self.client.post("/api/games", json={"engine": engine}, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()["gameId"]

    async def chat(self, game_id: str, message: str, **extra) -> list[dict]:
        body = {"message": message, "gameId": game_id, "provider": "anthropic", **extra}
        events: list[dict] = []
        async with self.client.stream("POST", "/api/chat", json=body, headers=self.headers) as r:
            assert r.status_code == 200, await r.aread()
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    async def drain(self, timeout: float = 10.0) -> None:
        """Wait for fire-and-forget tasks (extraction, director) spawned by the turn.

        Waits on every other task in the loop: production code only spawns turn-scoped
        tasks (api/routes.py create_task calls) and has no app-level background loop under
        the ASGI test client, so nothing long-lived is swept in. The bounded retry loop
        also covers tasks spawned by tasks.
        """
        current = asyncio.current_task()
        for _ in range(5):
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if not pending:
                return
            await asyncio.wait(pending, timeout=timeout)

    async def db_summary(self, game_id: str) -> dict[str, int]:
        """Row counts of every table holding a game_id column, for this game."""
        async with self.pool.acquire() as conn:
            tables = await conn.fetch(
                """SELECT table_name FROM information_schema.columns
                   WHERE column_name = 'game_id' AND table_schema = 'public'
                     AND table_name IN (SELECT table_name FROM information_schema.tables
                                        WHERE table_type = 'BASE TABLE')
                   ORDER BY table_name"""
            )
            summary = {}
            for row in tables:
                t = row["table_name"]
                summary[t] = await conn.fetchval(f'SELECT COUNT(*) FROM "{t}" WHERE game_id = $1', game_id)
            return summary

    @staticmethod
    def summarize(events: list[dict]) -> list[str]:
        """Event types with consecutive chunk/progress collapsed, e.g. ['status', 'chunk*', 'done']."""
        out: list[str] = []
        for e in events:
            t = e.get("type", "?")
            if t in ("chunk", "progress"):
                t = f"{t}*"
                if out and out[-1] == t:
                    continue
            out.append(t)
        return out

    async def init_world(self, game_id: str, engine: str = "none",
                         character_data: dict | None = None) -> list[dict]:
        extra = {"engine": engine, "world_config": {"genre": "sci_fi", "difficulty": "moderate"}}
        if character_data is not None:
            extra["character_data"] = character_data
        events = await self.chat(game_id, "__INIT__", **extra)
        await self.drain()
        return events

    def snapshot(self, events: list[dict], db: dict[str, int]) -> dict:
        return {
            "sse": self.summarize(events),
            # Sorted: extraction resolver and director run as concurrent tasks, so
            # their relative order is nondeterministic (observed flipping between runs).
            "llm_calls": sorted(self.llm.purposes()),
            "db_counts": db,
        }
