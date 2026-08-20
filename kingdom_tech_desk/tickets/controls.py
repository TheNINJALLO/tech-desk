from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import ui

from kingdom_tech_desk.constants import (
    MEMBER_INFO_RESPONSE_ID,
    TICKET_ADD_MEMBER_ID,
    TICKET_CLAIM_ID,
    TICKET_CLOSE_ID,
    TICKET_DUPLICATE_ID,
    TICKET_ESCALATE_ID,
    TICKET_INCIDENT_ID,
    TICKET_REMOVE_MEMBER_ID,
    TICKET_REQUEST_INFO_ID,
    TICKET_RESOLVE_ID,
    TICKET_SEVERITY_ID,
    TICKET_STATUS_ID,
    TICKET_UNCLAIM_ID,
)
from kingdom_tech_desk.models.core import ResolutionType, Severity, TicketRecord, TicketStatus
from kingdom_tech_desk.services.security import escape_markdown
from kingdom_tech_desk.tickets.permissions import require_staff

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

USER_ID_RE = re.compile(r"\d{15,22}")

REQUEST_FIELDS = [
    ("Exact reproduction steps", "steps"),
    ("Exact error message", "error_message"),
    ("Screenshot or video", "evidence"),
    ("Minecraft version", "client_version"),
    ("Coordinates or area", "location"),
    ("Time of occurrence", "time"),
    ("Item or transaction details", "transaction"),
    ("Another test attempt", "retest"),
]


def _radio_options(values: list[tuple[str, str]], selected: str | None = None) -> list[discord.RadioGroupOption]:
    return [
        discord.RadioGroupOption(label=label, value=value, default=value == selected)
        for label, value in values
    ]


def _checkbox_options(values: list[tuple[str, str]]) -> list[discord.CheckboxGroupOption]:
    return [discord.CheckboxGroupOption(label=label, value=value) for label, value in values]


def _paragraph(
    custom_id: str,
    *,
    default: str | None = None,
    required: bool = True,
    min_length: int | None = None,
    max_length: int = 1000,
    placeholder: str | None = None,
) -> ui.TextInput:
    return ui.TextInput(
        custom_id=custom_id,
        style=discord.TextStyle.paragraph,
        default=default,
        required=required,
        min_length=min_length,
        max_length=max_length,
        placeholder=placeholder,
    )


async def _staff_ticket(interaction: discord.Interaction) -> tuple[KingdomTechDeskBot, TicketRecord, discord.TextChannel] | None:
    if not await require_staff(interaction):
        return None
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This control must be used inside a technical ticket.", ephemeral=True)
        return None
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    ticket = await bot.tickets.get_by_channel(interaction.channel.id)
    if ticket is None:
        await interaction.response.send_message("This channel is not registered as a Kingdom Tech Desk ticket.", ephemeral=True)
        return None
    return bot, ticket, interaction.channel


async def _member_by_input(guild: discord.Guild, value: str) -> discord.Member | None:
    match = USER_ID_RE.search(value)
    if not match:
        return None
    user_id = int(match.group(0))
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None


class RequestInformationModal(ui.Modal):
    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Request More Information", custom_id=f"ktd:modal:request:{ticket.id}", timeout=900)
        self.ticket_id = ticket.id
        self.fields_input = ui.CheckboxGroup(
            custom_id=f"ktd:request:fields:{ticket.id}",
            required=True,
            min_values=1,
            max_values=len(REQUEST_FIELDS),
            options=_checkbox_options(REQUEST_FIELDS),
        )
        self.question_input = _paragraph(
            f"ktd:request:question:{ticket.id}",
            required=False,
            max_length=500,
            placeholder="Optional custom question for the member",
        )
        self.add_item(ui.Label(text="What information is missing?", component=self.fields_input))
        self.add_item(ui.Label(text="Optional custom question", component=self.question_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None or not isinstance(interaction.user, discord.Member):
            return
        bot, ticket, channel = context
        request = await bot.tickets.create_information_request(
            ticket.id,
            interaction.user.id,
            [str(value) for value in self.fields_input.values],
            self.question_input.value.strip() or None,
        )
        requested_labels = [label for label, value in REQUEST_FIELDS if value in request.requested_fields]
        lines = [
            f"<@{ticket.reporter_id}> staff need more information before testing can continue:",
            *[f"• {escape_markdown(label)}" for label in requested_labels],
        ]
        if request.custom_question:
            lines.append(f"\n**Question:** {escape_markdown(request.custom_question)}")
        lines.append("\nUse **Provide Requested Information** below. Do not replace the written answer with only a file.")
        await channel.send(
            "\n".join(lines)[:1900],
            view=MemberInformationView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.response.send_message(
            f"Information request #{request.id} posted. Status changed to **WAITING ON MEMBER**.",
            ephemeral=True,
        )


class MemberInformationResponseModal(ui.Modal):
    def __init__(self, ticket: TicketRecord, request_id: int) -> None:
        super().__init__(
            title="Provide Requested Information",
            custom_id=f"ktd:modal:info-response:{request_id}",
            timeout=900,
        )
        self.ticket_id = ticket.id
        self.request_id = request_id
        self.response_input = _paragraph(
            f"ktd:info:response:{request_id}",
            required=True,
            min_length=20,
            max_length=1800,
            placeholder="Answer each requested item with exact details.",
        )
        self.evidence_input = ui.FileUpload(
            custom_id=f"ktd:info:evidence:{request_id}",
            required=False,
            min_values=0,
            max_values=3,
        )
        self.add_item(
            ui.Label(
                text="Detailed response",
                description="Answer the staff request in writing. Media is optional and supplemental."[:100],
                component=self.response_input,
            )
        )
        self.add_item(ui.Label(text="Optional new evidence", component=self.evidence_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This response belongs inside the ticket channel.", ephemeral=True)
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        ticket = await bot.tickets.get_by_channel(interaction.channel.id)
        if ticket is None or ticket.id != self.ticket_id or interaction.user.id != ticket.reporter_id:
            await interaction.response.send_message("Only the reporting member can answer this request.", ephemeral=True)
            return
        response = self.response_input.value.strip()
        if len(response) < 20:
            await interaction.response.send_message("Add a more complete written answer before submitting.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        open_request = await bot.tickets.get_latest_open_information_request(ticket.id)
        await bot.tickets.respond_to_information_request(self.request_id, interaction.user.id, response)
        files: list[discord.File] = []
        evidence_notes: list[str] = []
        for attachment in self.evidence_input.values:
            try:
                files.append(await attachment.to_file())
            except discord.HTTPException:
                evidence_notes.append(f"Could not copy `{escape_markdown(attachment.filename)}`. Upload it in the channel.")
        mention_id = ticket.assignee_id or (open_request.requested_by if open_request else None)
        prefix = f"<@{mention_id}> " if mention_id else ""
        content = f"{prefix}**Requested information supplied by <@{ticket.reporter_id}>**\n{escape_markdown(response)}"
        if evidence_notes:
            content += "\n\n" + "\n".join(evidence_notes)
        send_kwargs: dict[str, object] = {
            "content": content[:1900],
            "allowed_mentions": discord.AllowedMentions(users=True, roles=False, everyone=False),
        }
        if files:
            send_kwargs["files"] = files[:3]
        await interaction.channel.send(**send_kwargs)  # type: ignore[arg-type]
        await interaction.followup.send(
            "✅ Your response was added and the ticket returned to **INVESTIGATING**.", ephemeral=True
        )


class MemberInformationView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Provide Requested Information",
        style=discord.ButtonStyle.primary,
        custom_id=MEMBER_INFO_RESPONSE_ID,
    )
    async def respond(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This control belongs inside a ticket channel.", ephemeral=True)
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        ticket = await bot.tickets.get_by_channel(interaction.channel.id)
        if ticket is None or interaction.user.id != ticket.reporter_id:
            await interaction.response.send_message("Only the reporting member can use this button.", ephemeral=True)
            return
        request = await bot.tickets.get_latest_open_information_request(ticket.id)
        if request is None:
            await interaction.response.send_message("There is no open information request on this ticket.", ephemeral=True)
            return
        await interaction.response.send_modal(MemberInformationResponseModal(ticket, request.id))


class StatusModal(ui.Modal):
    OPTIONS = [
        ("Open", TicketStatus.OPEN),
        ("Claimed", TicketStatus.CLAIMED),
        ("Investigating", TicketStatus.INVESTIGATING),
        ("Waiting on member", TicketStatus.WAITING_ON_MEMBER),
        ("Fix pending", TicketStatus.FIX_PENDING),
        ("Known issue", TicketStatus.KNOWN_ISSUE),
        ("Resolved", TicketStatus.RESOLVED),
    ]

    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Change Ticket Status", custom_id=f"ktd:modal:status:{ticket.id}", timeout=600)
        self.ticket_id = ticket.id
        self.status_input = ui.RadioGroup(
            custom_id=f"ktd:status:value:{ticket.id}",
            required=True,
            options=_radio_options([(label, str(value)) for label, value in self.OPTIONS], str(ticket.status)),
        )
        self.add_item(ui.Label(text="New status", component=self.status_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        status = TicketStatus(str(self.status_input.value))
        updated = await bot.tickets.set_status(ticket.id, status, interaction.user.id)
        await channel.send(
            f"Status changed to **{updated.status}** by {interaction.user.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.response.send_message(f"Status is now {updated.status}.", ephemeral=True)


class SeverityModal(ui.Modal):
    OPTIONS = [("Critical", Severity.CRITICAL), ("High", Severity.HIGH), ("Normal", Severity.NORMAL), ("Low", Severity.LOW)]

    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Change Ticket Severity", custom_id=f"ktd:modal:severity:{ticket.id}", timeout=600)
        self.ticket_id = ticket.id
        self.severity_input = ui.RadioGroup(
            custom_id=f"ktd:severity:value:{ticket.id}",
            required=True,
            options=_radio_options([(label, str(value)) for label, value in self.OPTIONS], str(ticket.severity)),
        )
        self.add_item(ui.Label(text="Confirmed severity", component=self.severity_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        severity = Severity(str(self.severity_input.value))
        updated = await bot.tickets.set_severity(ticket.id, severity, interaction.user.id)
        await channel.send(
            f"Severity confirmed as **{updated.severity}** by {interaction.user.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.response.send_message(f"Severity is now {updated.severity}.", ephemeral=True)


class ParticipantModal(ui.Modal):
    def __init__(self, ticket: TicketRecord, *, remove: bool) -> None:
        verb = "Remove" if remove else "Add"
        super().__init__(title=f"{verb} Ticket Member", custom_id=f"ktd:modal:participant:{verb.lower()}:{ticket.id}", timeout=600)
        self.ticket_id = ticket.id
        self.remove = remove
        self.member_input = ui.TextInput(
            custom_id=f"ktd:participant:user:{ticket.id}:{int(remove)}",
            placeholder="Paste a Discord user mention or numeric user ID",
            required=True,
            min_length=15,
            max_length=30,
        )
        self.add_item(ui.Label(text="Member mention or user ID", component=self.member_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None or interaction.guild is None:
            return
        bot, ticket, channel = context
        member = await _member_by_input(interaction.guild, self.member_input.value)
        if member is None:
            await interaction.response.send_message("That member could not be found in this server.", ephemeral=True)
            return
        if member.id == ticket.reporter_id and self.remove:
            await interaction.response.send_message("The original reporter cannot be removed from their ticket.", ephemeral=True)
            return
        if self.remove:
            await bot.tickets.remove_participant(ticket.id, member.id, interaction.user.id)
            await channel.set_permissions(member, overwrite=None, reason=f"Removed from KTS-{ticket.ticket_number:06d}")
            action = "removed from"
        else:
            await bot.tickets.add_participant(ticket.id, member.id, interaction.user.id)
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                reason=f"Added to KTS-{ticket.ticket_number:06d}",
            )
            action = "added to"
        await channel.send(
            f"{member.mention} was {action} this ticket by {interaction.user.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.response.send_message(f"Member {action} the ticket.", ephemeral=True)


class IncidentLinkModal(ui.Modal):
    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Link Ticket to Incident", custom_id=f"ktd:modal:incident:{ticket.id}", timeout=600)
        self.ticket_id = ticket.id
        self.identifier_input = ui.TextInput(
            custom_id=f"ktd:incident:identifier:{ticket.id}",
            placeholder="Existing INC-1234ABCD, or enter a new incident title",
            required=True,
            min_length=4,
            max_length=100,
        )
        self.notes_input = _paragraph(
            f"ktd:incident:notes:{ticket.id}",
            required=False,
            max_length=500,
            placeholder="Optional internal incident notes",
        )
        self.add_item(ui.Label(text="Incident ID or new title", component=self.identifier_input))
        self.add_item(ui.Label(text="Optional notes", component=self.notes_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        value = self.identifier_input.value.strip()
        incident = await bot.incidents.get_by_public_id(value) if value.upper().startswith("INC-") else None
        if incident is None:
            incident = await bot.incidents.create(
                guild_id=ticket.guild_id,
                title=value,
                category=str(ticket.data.get("category", "other")),
                created_by=interaction.user.id,
                notes=self.notes_input.value.strip() or None,
            )
        await bot.incidents.link_ticket(int(incident["id"]), ticket.id, interaction.user.id)
        await bot.tickets.add_event(
            ticket.id,
            "INCIDENT_LINKED",
            interaction.user.id,
            {"incident_id": incident["id"], "public_id": incident["public_id"]},
        )
        await channel.send(
            f"Linked to incident **{escape_markdown(str(incident['public_id']))} · {escape_markdown(str(incident['title']))}**."
        )
        await interaction.response.send_message(f"Linked to {incident['public_id']}.", ephemeral=True)


class DuplicateTicketModal(ui.Modal):
    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Mark as Duplicate", custom_id=f"ktd:modal:duplicate:{ticket.id}", timeout=600)
        self.ticket_id = ticket.id
        self.target_input = ui.TextInput(
            custom_id=f"ktd:duplicate:target:{ticket.id}",
            placeholder="KTS-000123 or 123",
            required=True,
            min_length=1,
            max_length=40,
        )
        self.reason_input = _paragraph(
            f"ktd:duplicate:reason:{ticket.id}",
            required=True,
            min_length=10,
            max_length=500,
            placeholder="Explain why these reports describe the same problem.",
        )
        self.add_item(ui.Label(text="Original ticket number", component=self.target_input))
        self.add_item(ui.Label(text="Duplicate reason", component=self.reason_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None or not isinstance(interaction.user, discord.Member):
            return
        bot, ticket, channel = context
        digits = re.findall(r"\d+", self.target_input.value)
        if not digits:
            await interaction.response.send_message("Enter a valid original ticket number.", ephemeral=True)
            return
        target = await bot.tickets.get_by_number(ticket.guild_id, int(digits[-1]))
        if target is None or target.id == ticket.id:
            await interaction.response.send_message("The original ticket could not be found.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await bot.tickets.add_event(
            ticket.id,
            "MARKED_DUPLICATE",
            interaction.user.id,
            {"target_ticket_id": target.id, "target_number": target.ticket_number, "reason": self.reason_input.value},
        )
        await bot.closure.close_ticket(
            channel,
            ticket,
            interaction.user,
            ResolutionType.DUPLICATE,
            self.reason_input.value.strip(),
            f"This report duplicates KTS-{target.ticket_number:06d}.",
            None,
        )
        await interaction.followup.send(
            f"Ticket closed as a duplicate of KTS-{target.ticket_number:06d}.", ephemeral=True
        )


class CloseTicketModal(ui.Modal):
    OPTIONS = [(value.replace("_", " ").title(), value) for value in ResolutionType]

    def __init__(self, ticket: TicketRecord) -> None:
        super().__init__(title="Close Technical Ticket", custom_id=f"ktd:modal:close:{ticket.id}", timeout=900)
        self.ticket_id = ticket.id
        self.resolution_input = ui.RadioGroup(
            custom_id=f"ktd:close:resolution:{ticket.id}",
            required=True,
            options=_radio_options([(label, str(value)) for label, value in self.OPTIONS]),
        )
        self.reason_input = _paragraph(
            f"ktd:close:reason:{ticket.id}",
            required=True,
            min_length=10,
            max_length=800,
            placeholder="Why is this ticket being closed?",
        )
        self.user_resolution_input = _paragraph(
            f"ktd:close:user:{ticket.id}",
            required=False,
            max_length=800,
            placeholder="Optional member-facing resolution or workaround",
        )
        self.internal_input = _paragraph(
            f"ktd:close:internal:{ticket.id}",
            required=False,
            max_length=800,
            placeholder="Optional internal note stored in the archive",
        )
        self.add_item(ui.Label(text="Resolution type", component=self.resolution_input))
        self.add_item(ui.Label(text="Closure reason", component=self.reason_input))
        self.add_item(ui.Label(text="Member-facing resolution", component=self.user_resolution_input))
        self.add_item(ui.Label(text="Internal note", component=self.internal_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        context = await _staff_ticket(interaction)
        if context is None or not isinstance(interaction.user, discord.Member):
            return
        bot, ticket, channel = context
        await interaction.response.defer(ephemeral=True, thinking=True)
        await bot.closure.close_ticket(
            channel,
            ticket,
            interaction.user,
            ResolutionType(str(self.resolution_input.value)),
            self.reason_input.value.strip(),
            self.user_resolution_input.value.strip() or None,
            self.internal_input.value.strip() or None,
        )
        await interaction.followup.send("Ticket closed and transcripts generated.", ephemeral=True)


class TicketControlsView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id=TICKET_CLAIM_ID, row=0)
    async def claim(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        updated = await bot.tickets.claim(ticket.id, interaction.user.id)
        await channel.send(
            f"Ticket claimed by {interaction.user.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.response.send_message(f"Claimed as assignee `{updated.assignee_id}`.", ephemeral=True)

    @ui.button(label="Unclaim", style=discord.ButtonStyle.secondary, custom_id=TICKET_UNCLAIM_ID, row=0)
    async def unclaim(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        await bot.tickets.unclaim(ticket.id, interaction.user.id)
        await channel.send(f"Ticket unclaimed by {interaction.user.mention}.")
        await interaction.response.send_message("Ticket returned to OPEN.", ephemeral=True)

    @ui.button(label="Request Information", style=discord.ButtonStyle.primary, custom_id=TICKET_REQUEST_INFO_ID, row=0)
    async def request_info(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(RequestInformationModal(ticket))

    @ui.button(label="Status", style=discord.ButtonStyle.secondary, custom_id=TICKET_STATUS_ID, row=0)
    async def status(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(StatusModal(ticket))

    @ui.button(label="Severity", style=discord.ButtonStyle.secondary, custom_id=TICKET_SEVERITY_ID, row=0)
    async def severity(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(SeverityModal(ticket))

    @ui.button(label="Add Member", style=discord.ButtonStyle.secondary, custom_id=TICKET_ADD_MEMBER_ID, row=1)
    async def add_member(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(ParticipantModal(ticket, remove=False))

    @ui.button(label="Remove Member", style=discord.ButtonStyle.secondary, custom_id=TICKET_REMOVE_MEMBER_ID, row=1)
    async def remove_member(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(ParticipantModal(ticket, remove=True))

    @ui.button(label="Escalate", style=discord.ButtonStyle.danger, custom_id=TICKET_ESCALATE_ID, row=1)
    async def escalate(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        config = await bot.guild_configs.get(ticket.guild_id)
        if ticket.severity in {Severity.NORMAL, Severity.LOW}:
            await bot.tickets.set_severity(ticket.id, Severity.HIGH, interaction.user.id)
        await bot.tickets.set_status(ticket.id, TicketStatus.INVESTIGATING, interaction.user.id)
        await bot.tickets.add_event(ticket.id, "ESCALATED", interaction.user.id, {})
        mentions = " ".join(f"<@&{role_id}>" for role_id in config.escalation_role_ids)
        await channel.send(
            f"{mentions}\n🚨 **Ticket escalated** by {interaction.user.mention}.".strip(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
        )
        await interaction.response.send_message("Ticket escalated.", ephemeral=True)

    @ui.button(label="Link Incident", style=discord.ButtonStyle.secondary, custom_id=TICKET_INCIDENT_ID, row=1)
    async def incident(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(IncidentLinkModal(ticket))

    @ui.button(label="Mark Duplicate", style=discord.ButtonStyle.secondary, custom_id=TICKET_DUPLICATE_ID, row=1)
    async def duplicate(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(DuplicateTicketModal(ticket))

    @ui.button(label="Resolve", style=discord.ButtonStyle.success, custom_id=TICKET_RESOLVE_ID, row=2)
    async def resolve(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        bot, ticket, channel = context
        await bot.tickets.set_status(ticket.id, TicketStatus.RESOLVED, interaction.user.id)
        await channel.send(f"Marked **RESOLVED** by {interaction.user.mention}. Close it when the resolution is documented.")
        await interaction.response.send_message("Ticket marked RESOLVED.", ephemeral=True)

    @ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id=TICKET_CLOSE_ID, row=2)
    async def close(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        context = await _staff_ticket(interaction)
        if context is None:
            return
        _bot, ticket, _channel = context
        await interaction.response.send_modal(CloseTicketModal(ticket))
