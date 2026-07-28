from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Any

import asyncpg


class Database:
    def __init__(self, url: str, min_size: int = 1, max_size: int = 5) -> None:
        self.url, self.min_size, self.max_size = url, min_size, max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.url, min_size=self.min_size, max_size=self.max_size, command_timeout=30)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def initialize_schema(self, path: Path | None = None) -> None:
        schema = (path or Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
        async with self.acquire() as connection:
            await connection.execute(schema)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        if self.pool is None:
            raise RuntimeError("Database pool is not connected")
        async with self.pool.acquire() as connection:
            yield connection
