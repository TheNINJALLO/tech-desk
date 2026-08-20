from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import ui

from kingdom_tech_desk.constants import (
    DRAFT_CANCEL_CONTEXT_ID,
    DRAFT_CANCEL_DETAILS_ID,
    DRAFT_CANCEL_DUPLICATE_ID,
    DRAFT_CANCEL_FAILED_ID,
    DRAFT_CONTINUE_CHECKS_ID,
    DRAFT_CONTINUE_DETAILS_ID,
    DRAFT_FIX_ID,
    DRAFT_REVIEW_DETAILS_ID,
    DRAFT_REVIEW_FAILED_ID,
    DRAFT_SUBMIT_ANYWAY_ID,
    DRAFT_SUBSCRIBE_MATCH_ID,
    DRAFT_VIEW_MATCHES_ID,
    PANEL_KNOWN_CUSTOM_ID,
    PANEL_RESUME_CUSTOM_ID,
    PANEL_START_CUSTOM_ID,
)
from kingdom_tech_desk.intake.panel import PANEL_MARKDOWN
from kingdom_tech_desk.intake.presentation import (
    draft_review_embed,
    known_issues_embed,
    validation_failure_message,
)
from kingdom_tech_desk.models.core import DraftRecord, DraftStage, DraftStatus
from kingdom_tech_desk.services.security import escape_markdown
from kingdom_tech_desk.tickets.creation import TicketCreationError

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

LOGGER = logging.getLogger(__name__)


async def _active_draft(interaction: discord.Interaction) -> DraftRecord | None:
    if interaction.guild is None:
        await interaction.response.send_message("Technical reports must be opened inside the server.", ephemeral=True)
        return None
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    draft = await bot.drafts.get_active(interaction.guild.id, interaction.user.id)
    if draft is None:
        await interaction.response.send_message(
            "No active technical-report draft was found. Use **Start Technical Report** first.", ephemeral=True
        )
        return None
    return draft


async def open_draft(interaction: discord.Interaction, draft: DraftRecord) -> None:
    from kingdom_tech_desk.intake.modals import ChecksModal, ContextModal, DetailsModal

    if draft.status == DraftStatus.SUBMITTING:
        await interaction.response.send_message(
            "This report is currently being submitted. Check for a newly created private ticket, then try Resume Draft.",
            ephemeral=True,
        )
        return
    if draft.current_stage <= DraftStage.CONTEXT:
        await interaction.response.send_modal(ContextModal(draft, interaction.user.id))
        return
    if draft.current_stage == DraftStage.DETAILS:
        await interaction.response.send_modal(DetailsModal(draft, interaction.user.id))
        return
    if draft.current_stage == DraftStage.CHECKS:
        await interaction.response.send_modal(ChecksModal(draft, interaction.user.id))
        return

    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    result = bot.validator.validate(draft.data)
    if not result.valid:
        target = result.failed_stage or DraftStage.CONTEXT
        if target == DraftStage.CONTEXT:
            await interaction.response.send_modal(ContextModal(draft, interaction.user.id))
        elif target == DraftStage.DETAILS:
            await interaction.response.send_modal(DetailsModal(draft, interaction.user.id))
        else:
            await interaction.response.send_modal(ChecksModal(draft, interaction.user.id))
        return

    matches = draft.data.get("duplicate_matches") or []
    if matches:
        await interaction.response.send_message(
            "Your report passed validation and has possible matches. Choose whether to subscribe or continue with a separate ticket.",
            ephemeral=True,
            view=DuplicateDecisionView(),
        )
        return

    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("The ticket could not be created outside a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        creation = await bot.ticket_creator.create(interaction.guild, interaction.user, draft)
    except TicketCreationError as exc:
        await interaction.followup.send(f"❌ {escape_markdown(str(exc))}"[:1900], ephemeral=True)
        return
    await interaction.followup.send(
        f"✅ **Technical ticket submitted:** {creation.channel.mention}", ephemeral=True
    )


async def start_or_resume(interaction: discord.Interaction, *, create: bool) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Technical reports must be opened inside the server.", ephemeral=True)
        return
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    allowed, _remaining = await bot.rate_limits.hit(
        interaction.guild.id,
        interaction.user.id,
        "draft_start" if create else "draft_resume",
        limit=6,
        window_seconds=60,
    )
    if not allowed:
        await interaction.response.send_message(
            "Too many report actions were requested at once. Pause briefly, then use Resume Draft.", ephemeral=True
        )
        return
    config = await bot.guild_configs.get(interaction.guild.id)
    if create:
        draft = await bot.drafts.create_or_get(
            interaction.guild.id,
            interaction.user.id,
            config.draft_expiry_hours,
        )
    else:
        draft = await bot.drafts.get_active(interaction.guild.id, interaction.user.id)
        if draft is None:
            await interaction.response.send_message(
                "No active draft was found. Start a new technical report.", ephemeral=True
            )
            return
    await open_draft(interaction, draft)


class PublicPanelActions(ui.ActionRow):
    @ui.button(
        label="Start Technical Report",
        style=discord.ButtonStyle.primary,
        emoji="🛠️",
        custom_id=PANEL_START_CUSTOM_ID,
    )
    async def start_report(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await start_or_resume(interaction, create=True)

    @ui.button(
        label="Resume Draft",
        style=discord.ButtonStyle.secondary,
        emoji="📝",
        custom_id=PANEL_RESUME_CUSTOM_ID,
    )
    async def resume_report(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await start_or_resume(interaction, create=False)

    @ui.button(
        label="View Known Issues",
        style=discord.ButtonStyle.secondary,
        emoji="📡",
        custom_id=PANEL_KNOWN_CUSTOM_ID,
    )
    async def known_issues(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Known issues are server-specific.", ephemeral=True)
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        issues = await bot.known_issues.list_active(interaction.guild.id)
        await interaction.response.send_message(embed=known_issues_embed(issues), ephemeral=True)


class PublicPanelView(ui.LayoutView):
    text = ui.TextDisplay(PANEL_MARKDOWN)
    separator = ui.Separator()
    actions = PublicPanelActions()

    def __init__(self) -> None:
        super().__init__(timeout=None)


class ContextSavedView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Continue: Describe the Problem",
        style=discord.ButtonStyle.primary,
        custom_id=DRAFT_CONTINUE_DETAILS_ID,
    )
    async def continue_details(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        from kingdom_tech_desk.intake.modals import DetailsModal

        await interaction.response.send_modal(DetailsModal(draft, interaction.user.id))

    @ui.button(label="Cancel Report", style=discord.ButtonStyle.danger, custom_id=DRAFT_CANCEL_CONTEXT_ID, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await prompt_cancel(interaction)


class DetailsSavedView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Continue: Checks and Evidence",
        style=discord.ButtonStyle.primary,
        custom_id=DRAFT_CONTINUE_CHECKS_ID,
    )
    async def continue_checks(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        from kingdom_tech_desk.intake.modals import ChecksModal

        await interaction.response.send_modal(ChecksModal(draft, interaction.user.id))

    @ui.button(label="Review Full Draft", style=discord.ButtonStyle.secondary, custom_id=DRAFT_REVIEW_DETAILS_ID)
    async def review(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await show_review(interaction)

    @ui.button(label="Cancel Report", style=discord.ButtonStyle.danger, custom_id=DRAFT_CANCEL_DETAILS_ID, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await prompt_cancel(interaction)


class FailedValidationView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Fix Missing Details", style=discord.ButtonStyle.primary, custom_id=DRAFT_FIX_ID)
    async def fix(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        result = bot.validator.validate(draft.data)
        from kingdom_tech_desk.intake.modals import ChecksModal, ContextModal, DetailsModal

        target = result.failed_stage or DraftStage.CONTEXT
        if target == DraftStage.CONTEXT:
            await interaction.response.send_modal(ContextModal(draft, interaction.user.id))
        elif target == DraftStage.DETAILS:
            await interaction.response.send_modal(DetailsModal(draft, interaction.user.id))
        else:
            await interaction.response.send_modal(ChecksModal(draft, interaction.user.id))

    @ui.button(label="Review Full Draft", style=discord.ButtonStyle.secondary, custom_id=DRAFT_REVIEW_FAILED_ID)
    async def review(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await show_review(interaction)

    @ui.button(label="Cancel Report", style=discord.ButtonStyle.danger, custom_id=DRAFT_CANCEL_FAILED_ID)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await prompt_cancel(interaction)


class DuplicateDecisionView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Continue With Separate Ticket",
        style=discord.ButtonStyle.primary,
        custom_id=DRAFT_SUBMIT_ANYWAY_ID,
    )
    async def continue_separate(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None or interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        result = bot.validator.validate(draft.data)
        if not result.valid:
            await interaction.response.send_message(
                validation_failure_message(result)[:1900], ephemeral=True, view=FailedValidationView()
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            creation = await bot.ticket_creator.create(interaction.guild, interaction.user, draft)
        except TicketCreationError as exc:
            await interaction.followup.send(f"❌ {escape_markdown(str(exc))}"[:1900], ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ **Separate technical ticket submitted:** {creation.channel.mention}", ephemeral=True
        )

    @ui.button(
        label="Subscribe to Known Issue",
        style=discord.ButtonStyle.success,
        custom_id=DRAFT_SUBSCRIBE_MATCH_ID,
    )
    async def subscribe(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        match = next(
            (item for item in draft.data.get("duplicate_matches", []) if item.get("kind") == "known_issue"),
            None,
        )
        if not match:
            await interaction.response.send_message(
                "No known-issue match is attached to this draft. You can continue with a separate ticket.",
                ephemeral=True,
            )
            return
        await bot.known_issues.subscribe(int(match["id"]), interaction.user.id)
        await interaction.response.send_message(
            f"✅ Subscribed to **{escape_markdown(str(match.get('public_id', 'known issue')))}**. "
            "Your draft remains available until you cancel it or submit separately.",
            ephemeral=True,
            view=DuplicateDecisionView(),
        )

    @ui.button(label="View Matches", style=discord.ButtonStyle.secondary, custom_id=DRAFT_VIEW_MATCHES_ID)
    async def matches(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        matches = draft.data.get("duplicate_matches", [])
        lines = [
            f"• **{escape_markdown(str(item.get('public_id') or item.get('kind')))}** · "
            f"{escape_markdown(str(item.get('title')))} · {round(float(item.get('score', 0)) * 100)}%"
            for item in matches
        ]
        await interaction.response.send_message(
            "# Possible matches\n" + ("\n".join(lines) if lines else "No stored matches."),
            ephemeral=True,
            view=DuplicateDecisionView(),
        )

    @ui.button(label="Cancel Report", style=discord.ButtonStyle.danger, custom_id=DRAFT_CANCEL_DUPLICATE_ID, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await prompt_cancel(interaction)


async def show_review(interaction: discord.Interaction) -> None:
    draft = await _active_draft(interaction)
    if draft is None:
        return
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    result = bot.validator.validate(draft.data)
    description = (
        "✅ The written report currently passes validation."
        if result.valid
        else f"❌ The draft currently has {len(result.errors)} validation issue(s)."
    )
    await interaction.response.send_message(
        content=description,
        embed=draft_review_embed(draft),
        ephemeral=True,
    )


class CancelConfirmView(ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=90)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the draft owner can cancel it.", ephemeral=True)
            return False
        return True

    @ui.button(label="Yes, Cancel and Delete Draft Evidence", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        draft = await _active_draft(interaction)
        if draft is None:
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        await bot.drafts.set_status(draft.id, DraftStatus.CANCELLED)
        await bot.evidence.cleanup_draft(draft.id)
        await interaction.response.edit_message(content="Technical-report draft cancelled.", view=None)

    @ui.button(label="Keep Draft", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await interaction.response.edit_message(content="Draft kept. Use Resume Draft when ready.", view=None)


async def prompt_cancel(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Cancel this technical report? Saved temporary evidence will be deleted.",
        ephemeral=True,
        view=CancelConfirmView(interaction.user.id),
    )
