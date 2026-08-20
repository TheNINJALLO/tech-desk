from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from kingdom_tech_desk.database.repositories.drafts import DraftRepository
from kingdom_tech_desk.database.repositories.guilds import GuildConfigRepository
from kingdom_tech_desk.database.repositories.tickets import TicketRepository
from kingdom_tech_desk.models.core import DraftRecord, DraftStatus, Severity, TicketRecord, TicketStatus
from kingdom_tech_desk.services.duplicate_detection import DuplicateDetectionService
from kingdom_tech_desk.services.evidence import EvidenceService
from kingdom_tech_desk.services.security import escape_markdown, ticket_channel_name
from kingdom_tech_desk.services.server_context import ServerContextProvider
from kingdom_tech_desk.services.severity import SeverityService
from kingdom_tech_desk.tickets.permissions import build_ticket_overwrites

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TicketCreationResult:
    ticket: TicketRecord
    channel: discord.TextChannel
    warnings: list[str]


class TicketCreationError(RuntimeError):
    pass


class TicketCreator:
    def __init__(
        self,
        bot: KingdomTechDeskBot,
        drafts: DraftRepository,
        tickets: TicketRepository,
        guild_configs: GuildConfigRepository,
        evidence: EvidenceService,
        severity: SeverityService,
        duplicates: DuplicateDetectionService,
        server_context: ServerContextProvider,
    ) -> None:
        self.bot = bot
        self.drafts = drafts
        self.tickets = tickets
        self.guild_configs = guild_configs
        self.evidence = evidence
        self.severity = severity
        self.duplicates = duplicates
        self.server_context = server_context
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    def _lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault((guild_id, user_id), asyncio.Lock())

    async def create(
        self,
        guild: discord.Guild,
        reporter: discord.Member,
        draft: DraftRecord,
    ) -> TicketCreationResult:
        async with self._lock(guild.id, reporter.id):
            if draft.guild_id != guild.id or draft.user_id != reporter.id:
                raise TicketCreationError("This technical-report draft does not belong to this member or server.")
            existing = await self.tickets.get_by_draft(draft.id)
            if existing and existing.channel_id:
                existing_channel = guild.get_channel(existing.channel_id)
                if isinstance(existing_channel, discord.TextChannel):
                    if existing.status != TicketStatus.CREATION_FAILED:
                        return TicketCreationResult(existing, existing_channel, [])
                    try:
                        await existing_channel.delete(
                            reason=f"Retrying failed technical ticket KTS-{existing.ticket_number:06d}"
                        )
                    except discord.HTTPException as exc:
                        raise TicketCreationError(
                            "A partial technical-ticket channel exists from an earlier failed attempt. "
                            "A server administrator must run /tech repair or remove that partial channel."
                        ) from exc
                await self.tickets.clear_channel_id(existing.id)
                existing.channel_id = None
            config = await self.guild_configs.get(guild.id)
            open_count = await self.tickets.count_open_for_member(guild.id, reporter.id)
            if open_count >= config.max_open_tickets:
                raise TicketCreationError(
                    f"You already have {open_count} open technical tickets. Resolve or close one before creating another."
                )

            claimed = await self.drafts.claim_for_submission(draft.id)
            if not claimed and not (existing and existing.status == TicketStatus.CREATION_FAILED):
                refreshed = await self.drafts.get(draft.id)
                if refreshed and refreshed.status == DraftStatus.SUBMITTED:
                    existing = await self.tickets.get_by_draft(draft.id)
                    if existing and existing.channel_id:
                        channel = guild.get_channel(existing.channel_id)
                        if isinstance(channel, discord.TextChannel):
                            return TicketCreationResult(existing, channel, [])
                raise TicketCreationError("This report is already being submitted. Use Resume Draft if no ticket appears.")

            recent_similar = await self.duplicates.count_similar_recent(
                guild.id,
                draft.data,
                self.bot.config.limits.similar_ticket_window_minutes,
            )
            suggested = self.severity.suggest(draft.data, recent_similar)
            snapshot = await self.server_context.snapshot(str(draft.data.get("server_key") or "default"))
            evidence_records = await self.drafts.list_evidence(draft.id)
            ticket_data = dict(draft.data)
            ticket_data["evidence_count"] = len(evidence_records)
            ticket_data["evidence_total_bytes"] = sum(record.size for record in evidence_records)
            ticket_data["evidence_direct_upload_count"] = sum(
                1 for record in evidence_records if record.requires_direct_upload
            )
            ticket_data["server_snapshot"] = snapshot.data if snapshot.available else {}
            ticket_data["server_snapshot_error"] = snapshot.error if not snapshot.available else None
            ticket_data["suggested_severity"] = str(suggested)

            if existing and existing.status == TicketStatus.CREATION_FAILED:
                ticket = existing
                await self.tickets.update_creation_data(ticket.id, severity=suggested, data=ticket_data)
                ticket.data = ticket_data
                ticket.severity = suggested
                await self.tickets.reset_creation(ticket.id)
            else:
                number = await self.tickets.reserve_number(guild.id)
                ticket = await self.tickets.create_pending(
                    guild_id=guild.id,
                    number=number,
                    draft_id=draft.id,
                    reporter_id=reporter.id,
                    severity=suggested,
                    data=ticket_data,
                )

            warnings: list[str] = []
            channel: discord.TextChannel | None = None
            try:
                category = guild.get_channel(config.open_category_id) if config.open_category_id else None
                if not isinstance(category, discord.CategoryChannel):
                    raise TicketCreationError(
                        "The open-ticket category is not configured. A server administrator must run /tech setup."
                    )
                bot_member = guild.me
                if bot_member is None and self.bot.user is not None:
                    bot_member = guild.get_member(self.bot.user.id) or await guild.fetch_member(self.bot.user.id)
                if bot_member is None:
                    raise TicketCreationError("The bot could not resolve its server member record.")

                overwrites = build_ticket_overwrites(guild, reporter, bot_member, config)
                channel = await guild.create_text_channel(
                    name=ticket_channel_name(ticket.ticket_number, str(draft.data.get("gamertag", reporter.name))),
                    category=category,
                    overwrites=overwrites,
                    topic=(
                        f"kingdom-tech-desk | KTS-{ticket.ticket_number:06d} | "
                        f"reporter={reporter.id} | draft={draft.public_id}"
                    )[:1024],
                    reason=f"Accepted technical report KTS-{ticket.ticket_number:06d}",
                )
                await self.tickets.attach_channel(ticket.id, channel.id)
                ticket.channel_id = channel.id

                from kingdom_tech_desk.tickets.controls import TicketControlsView

                embeds = self.build_intake_embeds(ticket, reporter, config.server_name, config.server_version)
                await channel.send(
                    content=(
                        f"Technical report **KTS-{ticket.ticket_number:06d}** was accepted. "
                        "Staff can claim it below."
                    ),
                    embeds=embeds,
                    view=TicketControlsView(),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

                for record in evidence_records:
                    if record.requires_direct_upload or not record.path or not record.path.exists():
                        warnings.append(
                            f"{record.original_name} was not copied automatically. Upload it directly in this channel."
                        )
                        continue
                    try:
                        message = await channel.send(
                            content=f"Evidence: `{escape_markdown(record.original_name)}`",
                            file=discord.File(record.path, filename=Path(record.original_name).name[:100]),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        await self.tickets.add_evidence_record(
                            ticket.id,
                            safe_name=record.safe_name,
                            original_name=record.original_name,
                            message_id=message.id,
                            content_type=record.content_type,
                            size=record.size,
                            media_kind=record.media_kind,
                        )
                    except (discord.HTTPException, OSError) as exc:
                        LOGGER.warning("Could not upload evidence for ticket %s: %s", ticket.id, type(exc).__name__)
                        warnings.append(f"{record.original_name} could not be copied. Upload it directly in this channel.")

                if warnings:
                    await channel.send(
                        "**Evidence notice**\n" + "\n".join(f"• {escape_markdown(item)}" for item in warnings),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

                if recent_similar + 1 >= self.bot.config.limits.possible_incident_threshold:
                    incident_channel = (
                        guild.get_channel(config.incident_channel_id) if config.incident_channel_id else None
                    )
                    if isinstance(incident_channel, discord.TextChannel):
                        try:
                            await incident_channel.send(
                                content=(
                                    "⚠️ **Possible technical incident cluster**\n"
                                    f"KTS-{ticket.ticket_number:06d} is the {recent_similar + 1}th similar "
                                    f"report inside {self.bot.config.limits.similar_ticket_window_minutes} minutes.\n"
                                    f"Category: `{escape_markdown(str(draft.data.get('category', 'other')))}`\n"
                                    f"Title: {escape_markdown(str(draft.data.get('title', 'Technical report')))}"
                                )[:1900],
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                            await self.tickets.add_event(
                                ticket.id,
                                "POSSIBLE_INCIDENT_CLUSTER",
                                None,
                                {"similar_reports": recent_similar + 1},
                            )
                        except discord.HTTPException:
                            LOGGER.warning("Could not post possible-incident alert for ticket %s", ticket.id)

                await self.drafts.set_status(draft.id, DraftStatus.SUBMITTED)
                await self.tickets.add_event(
                    ticket.id,
                    "REPORT_ACCEPTED",
                    reporter.id,
                    {"validation_score": draft.data.get("validation_score"), "warnings": warnings},
                )
                await self.evidence.cleanup_draft(draft.id)
                refreshed = await self.tickets.get(ticket.id)
                return TicketCreationResult(refreshed or ticket, channel, warnings)
            except Exception as exc:
                if channel is not None:
                    try:
                        await channel.delete(
                            reason=f"Cleaning up failed technical ticket KTS-{ticket.ticket_number:06d}"
                        )
                    except discord.HTTPException:
                        LOGGER.warning(
                            "Could not remove partial channel %s after ticket %s failed",
                            channel.id,
                            ticket.id,
                        )
                    else:
                        await self.tickets.clear_channel_id(ticket.id)
                        ticket.channel_id = None
                await self.tickets.mark_creation_failed(ticket.id, str(exc))
                await self.drafts.release_submission_claim(draft.id)
                if isinstance(exc, TicketCreationError):
                    raise
                raise TicketCreationError(
                    "The report passed validation, but Discord could not create the private ticket. Staff can use /tech repair."
                ) from exc

    @staticmethod
    def _field(embed: discord.Embed, name: str, value: Any, *, inline: bool = False) -> None:
        text = str(value or "Not supplied")
        if isinstance(value, list):
            text = ", ".join(str(item) for item in value) or "None"
        embed.add_field(name=name[:256], value=escape_markdown(text)[:1024] or "Not supplied", inline=inline)

    def build_intake_embeds(
        self,
        ticket: TicketRecord,
        reporter: discord.Member,
        server_name: str,
        server_version: str,
    ) -> list[discord.Embed]:
        data = ticket.data
        summary = discord.Embed(
            title=f"KTS-{ticket.ticket_number:06d} · {str(data.get('title', 'Technical report'))[:180]}",
            description="Structured intake captured before this private channel was created.",
            colour=discord.Colour.orange(),
            timestamp=ticket.created_at,
        )
        self._field(summary, "Reporter", f"{reporter} ({reporter.id})", inline=True)
        self._field(summary, "Gamertag", data.get("gamertag"), inline=True)
        self._field(summary, "Suggested severity", ticket.severity, inline=True)
        self._field(summary, "Category", data.get("category"), inline=True)
        self._field(summary, "Platform", data.get("platform"), inline=True)
        self._field(summary, "Affected", data.get("affected_scope"), inline=True)
        self._field(summary, "Minecraft client", data.get("client_version"), inline=True)
        self._field(summary, "Configured server", f"{server_name} · {server_version}", inline=True)
        self._field(summary, "Frequency", data.get("frequency"), inline=True)
        self._field(summary, "Where and when", data.get("where_when"))

        reproduction = discord.Embed(
            title="Reproduction and outcome",
            colour=discord.Colour.orange(),
        )
        self._field(reproduction, "Exact steps", data.get("steps"))
        self._field(reproduction, "Expected result", data.get("expected"))
        self._field(reproduction, "Actual result", data.get("actual"))
        self._field(reproduction, "Category-specific details", data.get("category_detail"))

        checks = discord.Embed(
            title="Checks, evidence, and server context",
            colour=discord.Colour.orange(),
        )
        self._field(checks, "Troubleshooting", data.get("troubleshooting"))
        self._field(checks, "Additional details", data.get("additional_details"))
        self._field(checks, "Evidence files", data.get("evidence_count", 0), inline=True)
        self._field(checks, "Evidence bytes", data.get("evidence_total_bytes", 0), inline=True)
        self._field(
            checks,
            "Direct upload needed",
            data.get("evidence_direct_upload_count", 0),
            inline=True,
        )
        snapshot = data.get("server_snapshot") or {}
        if snapshot:
            snapshot_text = "\n".join(f"{key}: {value}" for key, value in snapshot.items())
            self._field(checks, "Automatic server snapshot", snapshot_text)
        elif data.get("server_snapshot_error"):
            self._field(checks, "Automatic server snapshot", "Unavailable; ticket creation continued normally.")
        checks.set_footer(text="Screenshots and videos supplement the written report; they do not replace it.")
        return [summary, reproduction, checks]

    def build_intake_embed(
        self,
        ticket: TicketRecord,
        reporter: discord.Member,
        server_name: str,
        server_version: str,
    ) -> discord.Embed:
        """Compatibility helper returning the summary embed."""
        return self.build_intake_embeds(ticket, reporter, server_name, server_version)[0]
