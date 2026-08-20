from __future__ import annotations

import asyncio
import contextvars
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from kingdom_tech_desk.database.compat import Row, aiosqlite


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: Any | None = None
        self._lock = asyncio.Lock()
        self._inside_transaction: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "ktd_inside_transaction", default=False
        )

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = Row
        await self._execute_unlocked("PRAGMA foreign_keys = ON")
        await self._execute_unlocked("PRAGMA journal_mode = WAL")
        await self._execute_unlocked("PRAGMA synchronous = NORMAL")
        await self._execute_unlocked("PRAGMA busy_timeout = 5000")
        await self.connection.commit()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def _require_connection(self) -> Any:
        if self.connection is None:
            raise RuntimeError("Database is not connected")
        return self.connection

    async def _execute_unlocked(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        return await self._require_connection().execute(sql, parameters)

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        if self._inside_transaction.get():
            return await self._execute_unlocked(sql, parameters)
        async with self._lock:
            cursor = await self._execute_unlocked(sql, parameters)
            await self._require_connection().commit()
            return cursor

    async def executemany(self, sql: str, parameters: Iterable[Sequence[Any]]) -> Any:
        if self._inside_transaction.get():
            return await self._require_connection().executemany(sql, parameters)
        async with self._lock:
            cursor = await self._require_connection().executemany(sql, parameters)
            await self._require_connection().commit()
            return cursor

    async def executescript(self, script: str) -> None:
        async with self._lock:
            await self._require_connection().executescript(script)
            await self._require_connection().commit()

    async def fetchone(self, sql: str, parameters: Sequence[Any] = ()) -> Any | None:
        if self._inside_transaction.get():
            cursor = await self._execute_unlocked(sql, parameters)
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()
        async with self._lock:
            cursor = await self._execute_unlocked(sql, parameters)
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(self, sql: str, parameters: Sequence[Any] = ()) -> list[Any]:
        if self._inside_transaction.get():
            cursor = await self._execute_unlocked(sql, parameters)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()
        async with self._lock:
            cursor = await self._execute_unlocked(sql, parameters)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()

    @asynccontextmanager
    async def transaction(self, *, immediate: bool = True) -> AsyncIterator[None]:
        async with self._lock:
            token = self._inside_transaction.set(True)
            try:
                await self._execute_unlocked("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield
            except Exception:
                await self._require_connection().rollback()
                raise
            else:
                await self._require_connection().commit()
            finally:
                self._inside_transaction.reset(token)

    async def backup_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await self._execute_unlocked("PRAGMA wal_checkpoint(FULL)")
            # VACUUM INTO safely creates a consistent standalone database copy.
            escaped = str(destination).replace("'", "''")
            await self._execute_unlocked(f"VACUUM INTO '{escaped}'")
            await self._require_connection().commit()
