from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import discord

from kingdom_tech_desk.models.core import ResolutionType, TicketStatus

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

LOGGER = logging.getLogger(__name__)
TOPIC_TICKET_RE = re.compile(r"kingdom-tech-desk\s*\|\s*KTS-(\d{6})", re.IGNORECASE)


class MaintenanceService:
    def __init__(self, bot: KingdomTechDeskBot, interval_seconds: int = 900) -> None:
        self.bot = bot
        self.interval_seconds = max(60, interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._last_backup_date: date | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name="kingdom-tech-desk-maintenance")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self._stopping.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Maintenance cycle failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    async def run_once(self) -> None:
        expired_ids = await self.bot.drafts.expire_due()
        for draft_id in expired_ids:
            await self.bot.evidence.cleanup_draft(draft_id)

        await self._handle_waiting_tickets()
        await self._delete_closed_channels()

        today = datetime.now(UTC).date()
        if self._last_backup_date != today:
            try:
                await self.bot.backups.create()
                self._last_backup_date = today
            except Exception:
                LOGGER.exception("Daily SQLite backup failed")

    async def reconcile_startup(self) -> dict[str, int]:
        repaired = 0
        orphaned = 0
        missing_channels = 0
        for guild in self.bot.guilds:
            known_channel_ids = await self.bot.tickets.list_channel_ids(guild.id)
            for channel in guild.text_channels:
                topic = channel.topic or ""
                match = TOPIC_TICKET_RE.search(topic)
                if not match:
                    continue
                if channel.id in known_channel_ids:
                    continue
                number = int(match.group(1))
                ticket = await self.bot.tickets.get_by_number(guild.id, number)
                if ticket is not None and ticket.channel_id is None:
                    await self.bot.tickets.attach_channel(ticket.id, channel.id)
                    repaired += 1
                elif ticket is None:
                    orphaned += 1
                    LOGGER.warning("Unregistered KTD channel left untouched: %s (%s)", channel.name, channel.id)

        for ticket in await self.bot.tickets.list_without_channels():
            if ticket.status != TicketStatus.CREATION_FAILED:
                await self.bot.tickets.mark_creation_failed(ticket.id, "No Discord channel attached during startup reconciliation")
                missing_channels += 1
        return {"repaired": repaired, "orphaned": orphaned, "missing_channels": missing_channels}

    async def _handle_waiting_tickets(self) -> None:
        now = datetime.now(UTC)
        for ticket in await self.bot.tickets.list_waiting():
            guild = self.bot.get_guild(ticket.guild_id)
            if guild is None or ticket.channel_id is None:
                continue
            channel = guild.get_channel(ticket.channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            config = await self.bot.guild_configs.get(guild.id)
            elapsed_hours = (now - ticket.updated_at).total_seconds() / 3600

            if elapsed_hours >= config.waiting_auto_close_hours:
                bot_member = guild.me
                if bot_member is None:
                    continue
                try:
                    await self.bot.closure.close_ticket(
                        channel,
                        ticket,
                        bot_member,
                        ResolutionType.NO_RESPONSE,
                        "The requested technical information was not supplied before the inactivity deadline.",
                        "This ticket was closed after the requested information was not supplied. A new complete report may be submitted if the issue continues.",
                        "Automatically closed by the configured waiting-on-member lifecycle.",
                    )
                except Exception:
                    LOGGER.exception("Could not auto-close waiting ticket %s", ticket.id)
                continue

            if elapsed_hours >= config.waiting_second_reminder_hours:
                event_type = "WAITING_REMINDER_2"
                message = (
                    f"<@{ticket.reporter_id}> second reminder: staff are still waiting for the requested information. "
                    "Use the button above so the answer is attached to this ticket."
                )
            elif elapsed_hours >= config.waiting_reminder_hours:
                event_type = "WAITING_REMINDER_1"
                message = (
                    f"<@{ticket.reporter_id}> reminder: this ticket is waiting for additional information. "
                    "Use **Provide Requested Information** above."
                )
            else:
                continue

            if await self.bot.tickets.has_event(ticket.id, event_type):
                continue
            try:
                await channel.send(
                    message,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                await self.bot.tickets.add_event(ticket.id, event_type, self.bot.user.id if self.bot.user else None, {})
            except discord.HTTPException:
                LOGGER.warning("Could not send %s for ticket %s", event_type, ticket.id)

    async def _delete_closed_channels(self) -> None:
        for ticket in await self.bot.tickets.due_for_channel_deletion():
            if ticket.channel_id is None:
                continue
            guild = self.bot.get_guild(ticket.guild_id)
            channel = guild.get_channel(ticket.channel_id) if guild else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.delete(reason=f"KTS-{ticket.ticket_number:06d} archive retention elapsed")
                except discord.HTTPException:
                    LOGGER.warning("Could not delete closed ticket channel %s", ticket.channel_id)
                    continue
            # Clearing only the channel reference deliberately preserves ticket and transcript rows.
            await self.bot.tickets.clear_channel_id(ticket.id)
