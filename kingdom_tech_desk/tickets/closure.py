from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import discord

from kingdom_tech_desk.database.repositories.guilds import GuildConfigRepository
from kingdom_tech_desk.database.repositories.tickets import TicketRepository
from kingdom_tech_desk.models.core import ResolutionType, TicketRecord
from kingdom_tech_desk.services.transcripts import TranscriptService

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

LOGGER = logging.getLogger(__name__)


class ClosureService:
    def __init__(
        self,
        bot: KingdomTechDeskBot,
        tickets: TicketRepository,
        guild_configs: GuildConfigRepository,
        transcripts: TranscriptService,
    ) -> None:
        self.bot = bot
        self.tickets = tickets
        self.guild_configs = guild_configs
        self.transcripts = transcripts

    async def close_ticket(
        self,
        channel: discord.TextChannel,
        ticket: TicketRecord,
        actor: discord.Member,
        resolution_type: ResolutionType,
        closure_reason: str,
        user_resolution: str | None,
        internal_note: str | None,
    ) -> tuple[TicketRecord, tuple[Path, Path, Path]]:
        config = await self.guild_configs.get(channel.guild.id)
        messages = [message async for message in channel.history(limit=None, oldest_first=True)]
        # Record closure before rendering so the archive contains the final timeline.
        closed = await self.tickets.close(
            ticket.id,
            actor.id,
            resolution_type,
            closure_reason,
            user_resolution,
            internal_note,
            config.closed_retention_hours,
        )
        events = await self.tickets.list_events(ticket.id)
        paths = await asyncio.to_thread(self.transcripts.create, closed, messages, events)

        log_message_id: int | None = None
        log_channel = channel.guild.get_channel(config.log_channel_id) if config.log_channel_id else None
        if isinstance(log_channel, discord.TextChannel):
            try:
                log_message = await log_channel.send(
                    content=(
                        f"Closed **KTS-{ticket.ticket_number:06d}** · `{resolution_type}` · "
                        f"reporter `{ticket.reporter_id}`"
                    ),
                    files=[discord.File(path) for path in paths],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                log_message_id = log_message.id
            except (discord.HTTPException, OSError) as exc:
                LOGGER.error("Transcript upload failed for ticket %s: %s", ticket.id, type(exc).__name__)

        await self.tickets.add_transcript(
            ticket.id,
            str(paths[0]),
            str(paths[1]),
            str(paths[2]),
            log_message_id,
        )

        embed = discord.Embed(
            title=f"KTS-{ticket.ticket_number:06d} closed",
            description=user_resolution or closure_reason,
            colour=discord.Colour.dark_grey(),
        )
        embed.add_field(name="Resolution", value=str(resolution_type), inline=True)
        embed.add_field(name="Closed by", value=f"{actor} ({actor.id})", inline=True)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

        reporter = channel.guild.get_member(ticket.reporter_id)
        if reporter is None:
            try:
                reporter = await channel.guild.fetch_member(ticket.reporter_id)
            except discord.HTTPException:
                reporter = None
        member_ids = {ticket.reporter_id, *await self.tickets.list_participant_ids(ticket.id)}
        for member_id in member_ids:
            member = channel.guild.get_member(member_id)
            if member is None:
                try:
                    member = await channel.guild.fetch_member(member_id)
                except discord.HTTPException:
                    member = None
            if member is None:
                continue
            try:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    attach_files=False,
                    add_reactions=False,
                    reason=f"KTS-{ticket.ticket_number:06d} closed",
                )
            except discord.HTTPException:
                LOGGER.warning("Could not lock member %s for ticket %s", member_id, ticket.id)

        closed_category = channel.guild.get_channel(config.closed_category_id) if config.closed_category_id else None
        try:
            await channel.edit(
                name=f"closed-{ticket.ticket_number:06d}"[:100],
                category=closed_category if isinstance(closed_category, discord.CategoryChannel) else channel.category,
                reason=f"KTS-{ticket.ticket_number:06d} closed",
            )
        except discord.HTTPException:
            LOGGER.warning("Could not move or rename closed ticket %s", ticket.id)

        return closed, paths
