from __future__ import annotations

import io
import json
import tempfile
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from kingdom_tech_desk.intake.presentation import known_issues_embed
from kingdom_tech_desk.intake.views import PublicPanelView
from kingdom_tech_desk.models.core import DraftStatus, GuildConfig
from kingdom_tech_desk.services.security import escape_markdown
from kingdom_tech_desk.tickets.permissions import is_staff

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

MARKER = "kingdom-tech-desk"


def _admin(interaction: discord.Interaction) -> bool:
    return bool(
        isinstance(interaction.user, discord.Member)
        and (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator)
    )


async def _require_admin(interaction: discord.Interaction) -> bool:
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    if interaction.user.id in bot.config.owner_ids or _admin(interaction):
        return True
    await interaction.response.send_message("Manage Server permission is required for this command.", ephemeral=True)
    return False


def _find_marked_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return next(
        (
            channel
            for channel in guild.text_channels
            if channel.name == name and MARKER in (channel.topic or "").lower()
        ),
        None,
    )


def _directory_writable(path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".ktd-write-check-", dir=path):
            return True
    except OSError:
        return False


def _bot_category_overwrites(
    guild: discord.Guild,
    bot_member: discord.Member,
    support_role: discord.Role,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        support_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True,
        ),
    }


class TechCog(commands.GroupCog, group_name="tech", group_description="Kingdom Tech Desk administration"):
    panel = app_commands.Group(name="panel", description="Manage the technical-support panel")
    config_group = app_commands.Group(name="config", description="Configure Kingdom Tech Desk")
    known = app_commands.Group(name="known", description="Manage public known issues")
    incident = app_commands.Group(name="incident", description="Manage multi-ticket incidents")

    def __init__(self, bot: KingdomTechDeskBot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Create or bind Kingdom Tech Desk channels and roles")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        config = await self.bot.guild_configs.get(guild.id)
        bot_member = guild.me
        if bot_member is None:
            await interaction.followup.send("The bot member record is unavailable.", ephemeral=True)
            return

        support_role = guild.get_role(config.support_role_id) if config.support_role_id else None
        if support_role is None:
            support_role = await guild.create_role(
                name="Kingdom Tech Support",
                permissions=discord.Permissions.none(),
                mentionable=True,
                reason="Kingdom Tech Desk setup",
            )

        category_overwrites = _bot_category_overwrites(guild, bot_member, support_role)
        open_category = guild.get_channel(config.open_category_id) if config.open_category_id else None
        if not isinstance(open_category, discord.CategoryChannel):
            open_category = await guild.create_category(
                "TECH SUPPORT • OPEN",
                overwrites=category_overwrites,
                reason="Kingdom Tech Desk setup",
            )
        closed_category = guild.get_channel(config.closed_category_id) if config.closed_category_id else None
        if not isinstance(closed_category, discord.CategoryChannel):
            closed_category = await guild.create_category(
                "TECH SUPPORT • CLOSED",
                overwrites=category_overwrites,
                reason="Kingdom Tech Desk setup",
            )

        panel_channel = guild.get_channel(config.panel_channel_id) if config.panel_channel_id else None
        if not isinstance(panel_channel, discord.TextChannel):
            panel_channel = _find_marked_channel(guild, "tech-support")
        if panel_channel is None:
            panel_channel = await guild.create_text_channel(
                "tech-support",
                topic=f"{MARKER} | public technical-report panel",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    ),
                    support_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_messages=True,
                    ),
                    bot_member: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_messages=True,
                    ),
                },
                reason="Kingdom Tech Desk setup",
            )

        log_channel = guild.get_channel(config.log_channel_id) if config.log_channel_id else None
        if not isinstance(log_channel, discord.TextChannel):
            log_channel = _find_marked_channel(guild, "tech-ticket-logs")
        if log_channel is None:
            log_channel = await guild.create_text_channel(
                "tech-ticket-logs",
                category=closed_category,
                topic=f"{MARKER} | transcripts and audit exports",
                reason="Kingdom Tech Desk setup",
            )

        incident_channel = guild.get_channel(config.incident_channel_id) if config.incident_channel_id else None
        if not isinstance(incident_channel, discord.TextChannel):
            incident_channel = _find_marked_channel(guild, "tech-incidents")
        if incident_channel is None:
            incident_channel = await guild.create_text_channel(
                "tech-incidents",
                category=open_category,
                topic=f"{MARKER} | staff incident clustering",
                reason="Kingdom Tech Desk setup",
            )

        config.support_role_id = support_role.id
        config.open_category_id = open_category.id
        config.closed_category_id = closed_category.id
        config.panel_channel_id = panel_channel.id
        config.log_channel_id = log_channel.id
        config.incident_channel_id = incident_channel.id
        config.draft_expiry_hours = self.bot.config.limits.draft_expiry_hours
        config.max_open_tickets = self.bot.config.limits.max_open_tickets_per_member
        config.evidence_limit_bytes = self.bot.config.limits.automatic_evidence_bytes
        config.waiting_reminder_hours = self.bot.config.lifecycle.first_waiting_reminder_hours
        config.waiting_second_reminder_hours = self.bot.config.lifecycle.second_waiting_reminder_hours
        config.waiting_auto_close_hours = self.bot.config.lifecycle.auto_close_waiting_hours
        config.closed_retention_hours = self.bot.config.lifecycle.closed_channel_retention_hours
        config = await self.bot.guild_configs.update(config)

        panel_message = None
        if config.panel_message_id:
            try:
                panel_message = await panel_channel.fetch_message(config.panel_message_id)
            except discord.HTTPException:
                panel_message = None
        if panel_message is None:
            panel_message = await panel_channel.send(
                view=PublicPanelView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            config.panel_message_id = panel_message.id
            await self.bot.guild_configs.update(config)
        else:
            await panel_message.edit(view=PublicPanelView())

        await interaction.followup.send(
            "✅ Kingdom Tech Desk setup complete.\n"
            f"Panel: {panel_channel.mention}\n"
            f"Open tickets: `{open_category.name}`\n"
            f"Logs: {log_channel.mention}\n"
            f"Support role: {support_role.mention}",
            ephemeral=True,
        )

    @panel.command(name="send", description="Post a new technical-support panel")
    @app_commands.default_permissions(manage_guild=True)
    async def panel_send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        target = channel or (
            interaction.guild.get_channel(config.panel_channel_id) if config.panel_channel_id else None
        )
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Configure a panel channel or run /tech setup first.", ephemeral=True)
            return
        message = await target.send(view=PublicPanelView(), allowed_mentions=discord.AllowedMentions.none())
        await self.bot.guild_configs.patch(
            interaction.guild.id,
            panel_channel_id=target.id,
            panel_message_id=message.id,
        )
        await interaction.response.send_message(f"Technical panel posted in {target.mention}.", ephemeral=True)

    @panel.command(name="refresh", description="Refresh the configured persistent support panel")
    @app_commands.default_permissions(manage_guild=True)
    async def panel_refresh(self, interaction: discord.Interaction) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        channel = interaction.guild.get_channel(config.panel_channel_id) if config.panel_channel_id else None
        if not isinstance(channel, discord.TextChannel) or not config.panel_message_id:
            await interaction.response.send_message("No configured panel message was found.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(config.panel_message_id)
            await message.edit(view=PublicPanelView())
        except discord.HTTPException:
            await interaction.response.send_message("The saved panel message could not be edited. Use /tech panel send.", ephemeral=True)
            return
        await interaction.response.send_message("Persistent panel refreshed.", ephemeral=True)

    @config_group.command(name="view", description="Show the current technical-desk configuration")
    async def config_view(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        if not isinstance(interaction.user, discord.Member) or not is_staff(
            interaction.user, config, self.bot.config.owner_ids
        ):
            await interaction.response.send_message("Technical-support staff access is required.", ephemeral=True)
            return
        embed = discord.Embed(title="Kingdom Tech Desk configuration", colour=discord.Colour.blurple())
        for key, value in asdict(config).items():
            display = value
            if key.endswith("_id") and value:
                display = f"`{value}`"
            embed.add_field(name=key.replace("_", " ").title(), value=str(display), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="support-role", description="Set the technical-support role")
    @app_commands.default_permissions(manage_guild=True)
    async def config_support_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, support_role_id=role.id)
        await interaction.response.send_message(f"Support role set to {role.mention}.", ephemeral=True)

    @config_group.command(name="escalation-role", description="Add a role that receives escalated-ticket access")
    @app_commands.default_permissions(manage_guild=True)
    async def config_escalation_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        config.escalation_role_ids = sorted(set([*config.escalation_role_ids, role.id]))
        await self.bot.guild_configs.update(config)
        await interaction.response.send_message(f"Escalation role added: {role.mention}.", ephemeral=True)

    @config_group.command(name="open-category", description="Set the private open-ticket category")
    @app_commands.default_permissions(manage_guild=True)
    async def config_open_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, open_category_id=category.id)
        await interaction.response.send_message(f"Open category set to `{category.name}`.", ephemeral=True)

    @config_group.command(name="closed-category", description="Set the closed-ticket archive category")
    @app_commands.default_permissions(manage_guild=True)
    async def config_closed_category(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, closed_category_id=category.id)
        await interaction.response.send_message(f"Closed category set to `{category.name}`.", ephemeral=True)

    @config_group.command(name="log-channel", description="Set the transcript and audit-log channel")
    @app_commands.default_permissions(manage_guild=True)
    async def config_log_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, log_channel_id=channel.id)
        await interaction.response.send_message(f"Log channel set to {channel.mention}.", ephemeral=True)

    @config_group.command(name="server", description="Set the public server name used in reports")
    @app_commands.default_permissions(manage_guild=True)
    async def config_server(self, interaction: discord.Interaction, name: str) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, server_name=name[:100])
        await interaction.response.send_message(f"Server name set to `{escape_markdown(name[:100])}`.", ephemeral=True)

    @config_group.command(name="server-version", description="Set the configured BDS/server version")
    @app_commands.default_permissions(manage_guild=True)
    async def config_server_version(self, interaction: discord.Interaction, version: str) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, server_version=version[:100])
        await interaction.response.send_message(f"Server version set to `{escape_markdown(version[:100])}`.", ephemeral=True)

    @config_group.command(name="draft-expiry", description="Set draft retention in hours")
    @app_commands.default_permissions(manage_guild=True)
    async def config_draft_expiry(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 168]) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, draft_expiry_hours=int(hours))
        await interaction.response.send_message(f"Drafts now expire after {hours} hours.", ephemeral=True)

    @config_group.command(name="inactivity", description="Set reminder, auto-close, and archive timings")
    @app_commands.default_permissions(manage_guild=True)
    async def config_inactivity(
        self,
        interaction: discord.Interaction,
        first_reminder_hours: app_commands.Range[int, 1, 720],
        second_reminder_hours: app_commands.Range[int, 1, 720],
        auto_close_hours: app_commands.Range[int, 1, 1440],
        archive_hours: app_commands.Range[int, 1, 1440],
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        first = int(first_reminder_hours)
        second = int(second_reminder_hours)
        auto_close = int(auto_close_hours)
        archive = int(archive_hours)
        if not first < second < auto_close:
            await interaction.response.send_message(
                "Timings must be ordered: first reminder < second reminder < auto-close.",
                ephemeral=True,
            )
            return
        await self.bot.guild_configs.patch(
            interaction.guild.id,
            waiting_reminder_hours=first,
            waiting_second_reminder_hours=second,
            waiting_auto_close_hours=auto_close,
            closed_retention_hours=archive,
        )
        await interaction.response.send_message(
            f"Inactivity timing set to {first}h first reminder, {second}h second reminder, "
            f"{auto_close}h auto-close, and {archive}h archive retention.",
            ephemeral=True,
        )

    @config_group.command(name="max-open", description="Set maximum open tickets per member")
    @app_commands.default_permissions(manage_guild=True)
    async def config_max_open(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 20]) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await self.bot.guild_configs.patch(interaction.guild.id, max_open_tickets=int(count))
        await interaction.response.send_message(f"Members may have up to {count} open technical tickets.", ephemeral=True)

    @config_group.command(name="evidence-limit", description="Set automatic evidence copy limit in MiB")
    @app_commands.default_permissions(manage_guild=True)
    async def config_evidence_limit(
        self, interaction: discord.Interaction, mebibytes: app_commands.Range[int, 1, 100]
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        size = int(mebibytes) * 1024 * 1024
        await self.bot.guild_configs.patch(interaction.guild.id, evidence_limit_bytes=size)
        await interaction.response.send_message(f"Automatic evidence limit set to {mebibytes} MiB.", ephemeral=True)

    @known.command(name="add", description="Publish a known technical issue")
    @app_commands.default_permissions(manage_guild=True)
    async def known_add(
        self,
        interaction: discord.Interaction,
        title: str,
        category: str,
        workaround: str | None = None,
        internal_notes: str | None = None,
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        issue = await self.bot.known_issues.add(
            guild_id=interaction.guild.id,
            public_title=title[:180],
            category=category[:100],
            created_by=interaction.user.id,
            workaround=workaround[:1000] if workaround else None,
            internal_notes=internal_notes[:2000] if internal_notes else None,
        )
        await interaction.response.send_message(f"Known issue created: **{issue['public_id']}**.", ephemeral=True)

    @known.command(name="update", description="Update a known issue's title or workaround")
    @app_commands.default_permissions(manage_guild=True)
    async def known_update(
        self,
        interaction: discord.Interaction,
        issue_id: str,
        title: str | None = None,
        workaround: str | None = None,
        internal_notes: str | None = None,
    ) -> None:
        if not await _require_admin(interaction):
            return
        issue = await self.bot.known_issues.get_by_public_id(issue_id)
        if issue is None:
            await interaction.response.send_message("Known issue not found.", ephemeral=True)
            return
        updated = await self.bot.known_issues.update(
            int(issue["id"]),
            title=title[:180] if title else None,
            workaround=workaround[:1000] if workaround else None,
            internal_notes=internal_notes[:2000] if internal_notes else None,
        )
        await interaction.response.send_message(f"Updated {updated['public_id']}.", ephemeral=True)

    @known.command(name="resolve", description="Resolve a known issue")
    @app_commands.default_permissions(manage_guild=True)
    async def known_resolve(self, interaction: discord.Interaction, issue_id: str) -> None:
        if not await _require_admin(interaction):
            return
        issue = await self.bot.known_issues.get_by_public_id(issue_id)
        if issue is None:
            await interaction.response.send_message("Known issue not found.", ephemeral=True)
            return
        resolved = await self.bot.known_issues.resolve(int(issue["id"]))
        await interaction.response.send_message(f"Resolved {resolved['public_id']}.", ephemeral=True)

    @known.command(name="list", description="List active public known issues")
    async def known_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        issues = await self.bot.known_issues.list_active(interaction.guild.id)
        await interaction.response.send_message(embed=known_issues_embed(issues), ephemeral=True)

    @known.command(name="subscribe", description="Subscribe to a known issue")
    async def known_subscribe(self, interaction: discord.Interaction, issue_id: str) -> None:
        if interaction.guild is None:
            return
        issue = await self.bot.known_issues.get_by_public_id(issue_id)
        if issue is None or int(issue["guild_id"]) != interaction.guild.id:
            await interaction.response.send_message("Known issue not found in this server.", ephemeral=True)
            return
        await self.bot.known_issues.subscribe(int(issue["id"]), interaction.user.id)
        await interaction.response.send_message(f"Subscribed to {issue['public_id']}.", ephemeral=True)

    @incident.command(name="create", description="Create a master technical incident")
    @app_commands.default_permissions(manage_guild=True)
    async def incident_create(
        self,
        interaction: discord.Interaction,
        title: str,
        category: str,
        notes: str | None = None,
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        incident = await self.bot.incidents.create(
            guild_id=interaction.guild.id,
            title=title[:180],
            category=category[:100],
            created_by=interaction.user.id,
            notes=notes[:2000] if notes else None,
        )
        await interaction.response.send_message(f"Incident created: **{incident['public_id']}**.", ephemeral=True)

    @incident.command(name="list", description="List active incidents")
    async def incident_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        if not isinstance(interaction.user, discord.Member) or not is_staff(
            interaction.user, config, self.bot.config.owner_ids
        ):
            await interaction.response.send_message("Technical-support staff access is required.", ephemeral=True)
            return
        incidents = await self.bot.incidents.list_open(interaction.guild.id)
        text = "\n".join(
            f"• **{item['public_id']}** · {escape_markdown(str(item['title']))} · `{item['category']}`"
            for item in incidents[:20]
        ) or "No active incidents."
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @incident.command(name="resolve", description="Resolve a master incident")
    @app_commands.default_permissions(manage_guild=True)
    async def incident_resolve(self, interaction: discord.Interaction, incident_id: str) -> None:
        if not await _require_admin(interaction):
            return
        incident = await self.bot.incidents.get_by_public_id(incident_id)
        if incident is None:
            await interaction.response.send_message("Incident not found.", ephemeral=True)
            return
        resolved = await self.bot.incidents.resolve(int(incident["id"]))
        await interaction.response.send_message(f"Resolved {resolved['public_id']}.", ephemeral=True)

    @incident.command(name="link", description="Link a ticket number to an incident")
    @app_commands.default_permissions(manage_guild=True)
    async def incident_link(
        self,
        interaction: discord.Interaction,
        incident_id: str,
        ticket_number: int,
    ) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        incident = await self.bot.incidents.get_by_public_id(incident_id)
        ticket = await self.bot.tickets.get_by_number(interaction.guild.id, ticket_number)
        if incident is None or ticket is None:
            await interaction.response.send_message("Incident or ticket not found.", ephemeral=True)
            return
        await self.bot.incidents.link_ticket(int(incident["id"]), ticket.id, interaction.user.id)
        await self.bot.tickets.add_event(
            ticket.id,
            "INCIDENT_LINKED",
            interaction.user.id,
            {"incident_id": incident["id"], "public_id": incident["public_id"]},
        )
        await interaction.response.send_message(
            f"KTS-{ticket.ticket_number:06d} linked to {incident['public_id']}.", ephemeral=True
        )

    @app_commands.command(name="stats", description="Show technical support ticket statistics")
    async def stats(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        if not isinstance(interaction.user, discord.Member) or not is_staff(
            interaction.user, config, self.bot.config.owner_ids
        ):
            await interaction.response.send_message("Technical-support staff access is required.", ephemeral=True)
            return
        stats = await self.bot.tickets.stats(interaction.guild.id)
        embed = discord.Embed(title="Kingdom Tech Desk statistics", colour=discord.Colour.blurple())
        embed.add_field(
            name="Tickets by status",
            value="\n".join(f"{key}: {value}" for key, value in stats["by_status"].items()) or "None",
            inline=False,
        )
        embed.add_field(
            name="Tickets by severity",
            value="\n".join(f"{key}: {value}" for key, value in stats["by_severity"].items()) or "None",
            inline=False,
        )
        embed.add_field(name="Active drafts", value=str(stats["active_drafts"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="repair", description="Inspect permissions, storage, and ticket-channel state")
    @app_commands.default_permissions(manage_guild=True)
    async def repair(self, interaction: discord.Interaction) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        config = await self.bot.guild_configs.get(guild.id)
        bot_member = guild.me
        issues: list[str] = []
        if bot_member is None:
            issues.append("Bot member record unavailable")
        else:
            permissions = bot_member.guild_permissions
            required = {
                "Manage Channels": permissions.manage_channels,
                "Manage Roles": permissions.manage_roles,
                "Manage Messages": permissions.manage_messages,
                "View Channels": permissions.view_channel,
                "Send Messages": permissions.send_messages,
                "Attach Files": permissions.attach_files,
                "Embed Links": permissions.embed_links,
            }
            issues.extend(f"Missing permission: {name}" for name, available in required.items() if not available)
        persistent_names = {type(view).__name__ for view in self.bot.persistent_views}
        checks = {
            "Support role": bool(config.support_role_id and guild.get_role(config.support_role_id)),
            "Open category": isinstance(guild.get_channel(config.open_category_id), discord.CategoryChannel),
            "Closed category": isinstance(guild.get_channel(config.closed_category_id), discord.CategoryChannel),
            "Panel channel": isinstance(guild.get_channel(config.panel_channel_id), discord.TextChannel),
            "Log channel": isinstance(guild.get_channel(config.log_channel_id), discord.TextChannel),
            "Incident channel": isinstance(guild.get_channel(config.incident_channel_id), discord.TextChannel),
            "Message Content intent": self.bot.intents.message_content,
            "Database connected": self.bot.database.connection is not None,
            "Evidence directory writable": _directory_writable(self.bot.config.storage.evidence_dir),
            "Transcript directory writable": _directory_writable(self.bot.config.storage.transcript_dir),
            "Persistent panel registered": "PublicPanelView" in persistent_names,
            "Persistent ticket controls registered": "TicketControlsView" in persistent_names,
        }
        issues.extend(f"Failed check: {name}" for name, available in checks.items() if not available)
        reconciliation = await self.bot.maintenance.reconcile_startup()
        lines = [
            "# Kingdom Tech Desk repair report",
            *[f"• {name}: {'✅' if available else '❌'}" for name, available in checks.items()],
            f"• Reattached channels: {reconciliation['repaired']}",
            f"• Unregistered KTD channels left untouched: {reconciliation['orphaned']}",
            f"• Missing-channel records marked for retry: {reconciliation['missing_channels']}",
        ]
        if issues:
            lines.extend(["", "**Attention required**", *[f"• {escape_markdown(item)}" for item in issues]])
        else:
            lines.extend(["", "✅ No blocking configuration problems were found."])
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(name="export", description="Export non-secret configuration and ticket statistics")
    @app_commands.default_permissions(manage_guild=True)
    async def export(self, interaction: discord.Interaction) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        config = await self.bot.guild_configs.get(interaction.guild.id)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "guild_id": interaction.guild.id,
            "configuration": asdict(config),
            "statistics": await self.bot.tickets.stats(interaction.guild.id),
            "known_issues": await self.bot.known_issues.list_active(interaction.guild.id),
            "incidents": await self.bot.incidents.list_open(interaction.guild.id),
        }
        raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        await interaction.response.send_message(
            file=discord.File(io.BytesIO(raw), filename=f"kingdom-tech-desk-{interaction.guild.id}.json"),
            ephemeral=True,
        )

    @app_commands.command(name="privacy-delete", description="Delete drafts and anonymize a member's closed records")
    @app_commands.default_permissions(manage_guild=True)
    async def privacy_delete(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not await _require_admin(interaction) or interaction.guild is None:
            return
        active = await self.bot.tickets.count_open_for_member(interaction.guild.id, member.id)
        if active:
            await interaction.response.send_message(
                f"This member has {active} open technical ticket(s). Close those before anonymization.",
                ephemeral=True,
            )
            return
        for draft in await self.bot.drafts.list_for_user(interaction.guild.id, member.id):
            if draft.status != DraftStatus.SUBMITTED:
                await self.bot.evidence.cleanup_draft(draft.id)
        result = await self.bot.tickets.anonymize_user(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"Privacy cleanup complete. Draft records considered: {result['drafts']}; "
            f"closed tickets anonymized: {result['closed_tickets']}.",
            ephemeral=True,
        )
