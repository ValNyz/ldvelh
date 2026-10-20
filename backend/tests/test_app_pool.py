"""The DB pool lives on app.state, read by the get_pool dependency (#168)."""

import httpx
from fastapi import Depends, FastAPI

from api.dependencies import get_pool


async def test_pool_dependency_reads_app_state():
    sentinel = object()
    app = FastAPI()
    app.state.pool = sentinel

    @app.get("/pool")
    async def pool_route(pool=Depends(get_pool)):
        return {"same": pool is sentinel}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/pool")).json() == {"same": True}
