from __future__ import annotations

from dataclasses import asdict

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import dump_json, iso, load_json
from kingdom_tech_desk.models.core import GuildConfig


class GuildConfigRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def ensure(self, guild_id: int) -> GuildConfig:
        await self.database.execute(
            "INSERT OR IGNORE INTO guild_config(guild_id) VALUES (?)",
            (guild_id,),
        )
        return await self.get(guild_id)

    async def get(self, guild_id: int) -> GuildConfig:
        row = await self.database.fetchone("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,))
        if row is None:
            return await self.ensure(guild_id)
        return GuildConfig(
            guild_id=int(row["guild_id"]),
            support_role_id=row["support_role_id"],
            escalation_role_ids=[int(v) for v in load_json(row["escalation_role_ids_json"], [])],
            open_category_id=row["open_category_id"],
            closed_category_id=row["closed_category_id"],
            panel_channel_id=row["panel_channel_id"],
            panel_message_id=row["panel_message_id"],
            log_channel_id=row["log_channel_id"],
            incident_channel_id=row["incident_channel_id"],
            server_name=str(row["server_name"]),
            server_version=str(row["server_version"]),
            draft_expiry_hours=int(row["draft_expiry_hours"]),
            max_open_tickets=int(row["max_open_tickets"]),
            evidence_limit_bytes=int(row["evidence_limit_bytes"]),
            waiting_reminder_hours=int(row["waiting_reminder_hours"]),
            waiting_second_reminder_hours=int(row["waiting_second_reminder_hours"]),
            waiting_auto_close_hours=int(row["waiting_auto_close_hours"]),
            closed_retention_hours=int(row["closed_retention_hours"]),
        )

    async def update(self, config: GuildConfig) -> GuildConfig:
        data = asdict(config)
        await self.database.execute(
            """
            INSERT INTO guild_config(
                guild_id, support_role_id, escalation_role_ids_json, open_category_id,
                closed_category_id, panel_channel_id, panel_message_id, log_channel_id,
                incident_channel_id, server_name, server_version, draft_expiry_hours,
                max_open_tickets, evidence_limit_bytes, waiting_reminder_hours,
                waiting_second_reminder_hours, waiting_auto_close_hours,
                closed_retention_hours, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                support_role_id = excluded.support_role_id,
                escalation_role_ids_json = excluded.escalation_role_ids_json,
                open_category_id = excluded.open_category_id,
                closed_category_id = excluded.closed_category_id,
                panel_channel_id = excluded.panel_channel_id,
                panel_message_id = excluded.panel_message_id,
                log_channel_id = excluded.log_channel_id,
                incident_channel_id = excluded.incident_channel_id,
                server_name = excluded.server_name,
                server_version = excluded.server_version,
                draft_expiry_hours = excluded.draft_expiry_hours,
                max_open_tickets = excluded.max_open_tickets,
                evidence_limit_bytes = excluded.evidence_limit_bytes,
                waiting_reminder_hours = excluded.waiting_reminder_hours,
                waiting_second_reminder_hours = excluded.waiting_second_reminder_hours,
                waiting_auto_close_hours = excluded.waiting_auto_close_hours,
                closed_retention_hours = excluded.closed_retention_hours,
                updated_at = excluded.updated_at
            """,
            (
                config.guild_id,
                config.support_role_id,
                dump_json(config.escalation_role_ids),
                config.open_category_id,
                config.closed_category_id,
                config.panel_channel_id,
                config.panel_message_id,
                config.log_channel_id,
                config.incident_channel_id,
                config.server_name,
                config.server_version,
                config.draft_expiry_hours,
                config.max_open_tickets,
                config.evidence_limit_bytes,
                config.waiting_reminder_hours,
                config.waiting_second_reminder_hours,
                config.waiting_auto_close_hours,
                config.closed_retention_hours,
                iso(),
            ),
        )
        return await self.get(config.guild_id)

    async def patch(self, guild_id: int, **changes: object) -> GuildConfig:
        config = await self.get(guild_id)
        for key, value in changes.items():
            if key not in asdict(config):
                raise KeyError(f"Unknown guild configuration field: {key}")
            setattr(config, key, value)
        return await self.update(config)
