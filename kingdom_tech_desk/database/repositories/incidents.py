from __future__ import annotations

from typing import Any

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import iso, public_id


class IncidentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _map(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "guild_id": int(row["guild_id"]),
            "public_id": str(row["public_id"]),
            "title": str(row["title"]),
            "category": str(row["category"]),
            "status": str(row["status"]),
            "notes": row["notes"],
            "created_by": int(row["created_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "resolved_at": row["resolved_at"],
        }

    async def create(
        self,
        *,
        guild_id: int,
        title: str,
        category: str,
        created_by: int,
        notes: str | None = None,
    ) -> dict[str, Any]:
        identifier = public_id("INC", 4)
        now = iso()
        cursor = await self.database.execute(
            """
            INSERT INTO incidents(guild_id, public_id, title, category, status, notes, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            (guild_id, identifier, title, category, notes, created_by, now, now),
        )
        incident = await self.get(int(cursor.lastrowid))
        if incident is None:
            raise RuntimeError("Incident insert succeeded but could not be read")
        return incident

    async def get(self, incident_id: int) -> dict[str, Any] | None:
        row = await self.database.fetchone("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        return self._map(row) if row else None

    async def get_by_public_id(self, identifier: str) -> dict[str, Any] | None:
        row = await self.database.fetchone(
            "SELECT * FROM incidents WHERE upper(public_id) = upper(?)",
            (identifier,),
        )
        return self._map(row) if row else None

    async def list_open(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.database.fetchall(
            "SELECT * FROM incidents WHERE guild_id = ? AND status = 'OPEN' ORDER BY created_at DESC",
            (guild_id,),
        )
        return [self._map(row) for row in rows]

    async def link_ticket(self, incident_id: int, ticket_id: int, linked_by: int) -> None:
        await self.database.execute(
            """
            INSERT OR IGNORE INTO incident_tickets(incident_id, ticket_id, linked_by, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (incident_id, ticket_id, linked_by, iso()),
        )

    async def ticket_ids(self, incident_id: int) -> list[int]:
        rows = await self.database.fetchall(
            "SELECT ticket_id FROM incident_tickets WHERE incident_id = ? ORDER BY created_at",
            (incident_id,),
        )
        return [int(row["ticket_id"]) for row in rows]

    async def resolve(self, incident_id: int) -> dict[str, Any]:
        await self.database.execute(
            "UPDATE incidents SET status = 'RESOLVED', resolved_at = ?, updated_at = ? WHERE id = ?",
            (iso(), iso(), incident_id),
        )
        incident = await self.get(incident_id)
        if incident is None:
            raise LookupError("Incident not found")
        return incident
