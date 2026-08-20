from __future__ import annotations

from datetime import timedelta

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import iso, parse_dt, utcnow


class RateLimitService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def hit(
        self,
        guild_id: int,
        user_id: int,
        action: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        now = utcnow()
        async with self.database.transaction():
            row = await self.database.fetchone(
                "SELECT window_started_at, attempts FROM rate_limits WHERE guild_id = ? AND user_id = ? AND action = ?",
                (guild_id, user_id, action),
            )
            if row is None or (parse_dt(row["window_started_at"]) or now) + timedelta(seconds=window_seconds) <= now:
                attempts = 1
                await self.database.execute(
                    """
                    INSERT INTO rate_limits(guild_id, user_id, action, window_started_at, attempts)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(guild_id, user_id, action) DO UPDATE SET
                        window_started_at = excluded.window_started_at, attempts = 1
                    """,
                    (guild_id, user_id, action, iso(now)),
                )
            else:
                attempts = int(row["attempts"]) + 1
                await self.database.execute(
                    "UPDATE rate_limits SET attempts = ? WHERE guild_id = ? AND user_id = ? AND action = ?",
                    (attempts, guild_id, user_id, action),
                )
        return attempts <= limit, max(0, limit - attempts)
