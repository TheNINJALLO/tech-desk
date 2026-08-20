from __future__ import annotations

from typing import Any

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import dump_json, iso, load_json, public_id


class KnownIssueRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add(
        self,
        *,
        guild_id: int,
        public_title: str,
        category: str,
        created_by: int,
        workaround: str | None = None,
        internal_notes: str | None = None,
        platforms: list[str] | None = None,
        servers: list[str] | None = None,
    ) -> dict[str, Any]:
        now = iso()
        identifier = public_id("KI", 4)
        cursor = await self.database.execute(
            """
            INSERT INTO known_issues(
                guild_id, public_id, public_title, internal_notes, category,
                affected_platforms_json, affected_servers_json, status, workaround,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
            """,
            (
                guild_id,
                identifier,
                public_title,
                internal_notes,
                category,
                dump_json(platforms or []),
                dump_json(servers or []),
                workaround,
                created_by,
                now,
                now,
            ),
        )
        issue = await self.get(int(cursor.lastrowid))
        if issue is None:
            raise RuntimeError("Known issue insert succeeded but row could not be read")
        return issue

    def _map(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "guild_id": int(row["guild_id"]),
            "public_id": str(row["public_id"]),
            "public_title": str(row["public_title"]),
            "internal_notes": row["internal_notes"],
            "category": str(row["category"]),
            "platforms": load_json(row["affected_platforms_json"], []),
            "servers": load_json(row["affected_servers_json"], []),
            "status": str(row["status"]),
            "workaround": row["workaround"],
            "created_by": int(row["created_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "resolved_at": row["resolved_at"],
        }

    async def get(self, issue_id: int) -> dict[str, Any] | None:
        row = await self.database.fetchone("SELECT * FROM known_issues WHERE id = ?", (issue_id,))
        return self._map(row) if row else None

    async def get_by_public_id(self, public_identifier: str) -> dict[str, Any] | None:
        row = await self.database.fetchone(
            "SELECT * FROM known_issues WHERE public_id = ?",
            (public_identifier,),
        )
        return self._map(row) if row else None

    async def list_active(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.database.fetchall(
            "SELECT * FROM known_issues WHERE guild_id = ? AND status = 'ACTIVE' ORDER BY created_at DESC",
            (guild_id,),
        )
        return [self._map(row) for row in rows]

    async def update(
        self,
        issue_id: int,
        *,
        title: str | None = None,
        workaround: str | None = None,
        internal_notes: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        issue = await self.get(issue_id)
        if issue is None:
            raise LookupError("Known issue not found")
        await self.database.execute(
            """
            UPDATE known_issues SET public_title = ?, workaround = ?, internal_notes = ?,
                status = ?, updated_at = ? WHERE id = ?
            """,
            (
                title if title is not None else issue["public_title"],
                workaround if workaround is not None else issue["workaround"],
                internal_notes if internal_notes is not None else issue["internal_notes"],
                status if status is not None else issue["status"],
                iso(),
                issue_id,
            ),
        )
        updated = await self.get(issue_id)
        if updated is None:
            raise RuntimeError("Known issue vanished after update")
        return updated

    async def resolve(self, issue_id: int) -> dict[str, Any]:
        await self.database.execute(
            "UPDATE known_issues SET status = 'RESOLVED', resolved_at = ?, updated_at = ? WHERE id = ?",
            (iso(), iso(), issue_id),
        )
        issue = await self.get(issue_id)
        if issue is None:
            raise LookupError("Known issue not found")
        return issue

    async def subscribe(self, issue_id: int, user_id: int) -> None:
        await self.database.execute(
            """
            INSERT OR IGNORE INTO known_issue_subscribers(known_issue_id, user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (issue_id, user_id, iso()),
        )

    async def unsubscribe(self, issue_id: int, user_id: int) -> None:
        await self.database.execute(
            "DELETE FROM known_issue_subscribers WHERE known_issue_id = ? AND user_id = ?",
            (issue_id, user_id),
        )
