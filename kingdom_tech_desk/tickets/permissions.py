from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import discord

from kingdom_tech_desk.models.core import GuildConfig

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot


def is_staff(member: discord.Member, config: GuildConfig, owner_ids: set[int]) -> bool:
    if member.id in owner_ids or member.guild_permissions.administrator:
        return True
    allowed = {role_id for role_id in [config.support_role_id, *config.escalation_role_ids] if role_id}
    return any(role.id in allowed for role in member.roles)


def build_ticket_overwrites(
    guild: discord.Guild,
    reporter: discord.Member,
    bot_member: discord.Member,
    config: GuildConfig,
    participants: Iterable[discord.Member] = (),
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        reporter: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            add_reactions=True,
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
    role_ids = [config.support_role_id, *config.escalation_role_ids]
    for role_id in role_ids:
        if not role_id:
            continue
        role = guild.get_role(role_id)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            )
    for participant in participants:
        overwrites[participant] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )
    return overwrites


async def require_staff(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("This control can only be used inside the server.", ephemeral=True)
        return False
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    config = await bot.guild_configs.get(interaction.guild.id)
    if not is_staff(interaction.user, config, bot.config.owner_ids):
        await interaction.response.send_message("Only configured technical-support staff can use this control.", ephemeral=True)
        return False
    return True
