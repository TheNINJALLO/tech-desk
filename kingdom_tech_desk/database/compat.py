from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised in production with the real dependency
    import aiosqlite as _aiosqlite

    aiosqlite = _aiosqlite
    Row = _aiosqlite.Row
except ImportError:  # Lightweight fallback lets pure logic and DB tests run offline.
    Row = sqlite3.Row

    class _Cursor:
        def __init__(self, cursor: sqlite3.Cursor) -> None:
            self._cursor = cursor
            self.lastrowid = cursor.lastrowid
            self.rowcount = cursor.rowcount

        async def fetchone(self) -> sqlite3.Row | None:
            return await asyncio.to_thread(self._cursor.fetchone)

        async def fetchall(self) -> list[sqlite3.Row]:
            return await asyncio.to_thread(self._cursor.fetchall)

        async def close(self) -> None:
            await asyncio.to_thread(self._cursor.close)

    class _Connection:
        def __init__(self, path: str | Path) -> None:
            self._conn = sqlite3.connect(str(path), check_same_thread=False)

        @property
        def row_factory(self) -> Any:
            return self._conn.row_factory

        @row_factory.setter
        def row_factory(self, value: Any) -> None:
            self._conn.row_factory = value

        async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> _Cursor:
            cursor = await asyncio.to_thread(self._conn.execute, sql, parameters)
            return _Cursor(cursor)

        async def executemany(self, sql: str, parameters: Iterable[Sequence[Any]]) -> _Cursor:
            cursor = await asyncio.to_thread(self._conn.executemany, sql, list(parameters))
            return _Cursor(cursor)

        async def executescript(self, script: str) -> _Cursor:
            cursor = await asyncio.to_thread(self._conn.executescript, script)
            return _Cursor(cursor)

        async def commit(self) -> None:
            await asyncio.to_thread(self._conn.commit)

        async def rollback(self) -> None:
            await asyncio.to_thread(self._conn.rollback)

        async def close(self) -> None:
            await asyncio.to_thread(self._conn.close)

    class _AioSqliteFallback:
        Row = sqlite3.Row

        @staticmethod
        async def connect(path: str | Path) -> _Connection:
            return _Connection(path)

    aiosqlite = _AioSqliteFallback()
