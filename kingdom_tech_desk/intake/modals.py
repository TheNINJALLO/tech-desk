from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from kingdom_tech_desk.constants import (
    AFFECTED_OPTIONS,
    CATEGORY_PROMPTS,
    FREQUENCY_OPTIONS,
    ISSUE_OPTIONS,
    PLATFORM_OPTIONS,
    TROUBLESHOOTING_OPTIONS,
)
from kingdom_tech_desk.intake.presentation import validation_failure_message
from kingdom_tech_desk.models.core import DraftRecord, DraftStage, IssueCategory
from kingdom_tech_desk.services.security import escape_markdown
from kingdom_tech_desk.tickets.creation import TicketCreationError

if TYPE_CHECKING:
    from kingdom_tech_desk.bot import KingdomTechDeskBot

LOGGER = logging.getLogger(__name__)


def _radio_options(options: list[tuple[str, str]], selected: Any = None) -> list[discord.RadioGroupOption]:
    selected_value = str(selected or "")
    return [
        discord.RadioGroupOption(label=label[:100], value=str(value)[:100], default=str(value) == selected_value)
        for label, value in options
    ]


def _checkbox_options(
    options: list[tuple[str, str]], selected: list[str] | None = None
) -> list[discord.CheckboxGroupOption]:
    selected_values = {str(item) for item in (selected or [])}
    return [
        discord.CheckboxGroupOption(
            label=label[:100],
            value=str(value)[:100],
            default=str(value) in selected_values,
        )
        for label, value in options
    ]


def _text(
    *,
    custom_id: str,
    style: discord.TextStyle = discord.TextStyle.short,
    default: Any = None,
    placeholder: str | None = None,
    required: bool = True,
    min_length: int | None = None,
    max_length: int | None = None,
) -> ui.TextInput:
    return ui.TextInput(
        custom_id=custom_id[:100],
        style=style,
        default=str(default)[: min(max_length or 4000, 4000)] if default not in (None, "") else None,
        placeholder=placeholder[:100] if placeholder else None,
        required=required,
        min_length=min_length,
        max_length=max_length,
    )


async def _owned_draft(interaction: discord.Interaction, draft_id: int, user_id: int) -> DraftRecord | None:
    bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
    draft = await bot.drafts.get(draft_id)
    if draft is None or draft.user_id != user_id or interaction.user.id != user_id:
        if interaction.response.is_done():
            await interaction.followup.send("This technical-report draft does not belong to you.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "This technical-report draft does not belong to you.", ephemeral=True
            )
        return None
    return draft


class DraftModal(ui.Modal):
    def __init__(self, *, title: str, draft: DraftRecord, user_id: int, stage: DraftStage) -> None:
        super().__init__(
            title=title[:45],
            timeout=900,
            custom_id=f"ktd:modal:{stage.name.lower()}:{draft.public_id}"[:100],
        )
        self.draft_id = draft.id
        self.user_id = user_id
        self.stage = stage

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the draft owner can submit this form.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        LOGGER.exception("Draft modal failed", exc_info=error)
        message = "The form could not be saved. Your earlier completed stages are still preserved."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class ContextModal(DraftModal):
    def __init__(self, draft: DraftRecord, user_id: int) -> None:
        super().__init__(title="Step 1 of 3: Issue Context", draft=draft, user_id=user_id, stage=DraftStage.CONTEXT)
        data = draft.data
        self.category_input = ui.RadioGroup(
            custom_id=f"ktd:input:category:{draft.public_id}"[:100],
            required=True,
            options=_radio_options(ISSUE_OPTIONS, data.get("category")),
        )
        self.platform_input = ui.RadioGroup(
            custom_id=f"ktd:input:platform:{draft.public_id}"[:100],
            required=True,
            options=_radio_options(PLATFORM_OPTIONS, data.get("platform")),
        )
        self.scope_input = ui.RadioGroup(
            custom_id=f"ktd:input:scope:{draft.public_id}"[:100],
            required=True,
            options=_radio_options(AFFECTED_OPTIONS, data.get("affected_scope")),
        )
        self.gamertag_input = _text(
            custom_id=f"ktd:input:gamertag:{draft.public_id}",
            default=data.get("gamertag"),
            placeholder="Your exact Minecraft gamertag",
            min_length=3,
            max_length=32,
        )
        self.where_when_input = _text(
            custom_id=f"ktd:input:where:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("where_when"),
            placeholder="The Kingdom, Overworld shopping district, around 8:15 PM...",
            min_length=15,
            max_length=500,
        )
        self.add_item(ui.Label(text="Issue category", component=self.category_input))
        self.add_item(ui.Label(text="Device or platform", component=self.platform_input))
        self.add_item(ui.Label(text="Who is affected?", component=self.scope_input))
        self.add_item(ui.Label(text="Minecraft gamertag", component=self.gamertag_input))
        self.add_item(
            ui.Label(
                text="Where and approximately when?",
                description="Include server/world, area, coordinates when available, and approximate time."[:100],
                component=self.where_when_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = await _owned_draft(interaction, self.draft_id, self.user_id)
        if draft is None or interaction.guild is None:
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        config = await bot.guild_configs.get(interaction.guild.id)
        await bot.drafts.save_stage(
            draft.id,
            DraftStage.CONTEXT,
            {
                "category": str(self.category_input.value or ""),
                "platform": str(self.platform_input.value or ""),
                "affected_scope": str(self.scope_input.value or ""),
                "gamertag": self.gamertag_input.value.strip(),
                "where_when": self.where_when_input.value.strip(),
            },
            config.draft_expiry_hours,
        )
        from kingdom_tech_desk.intake.views import ContextSavedView

        await interaction.response.send_message(
            "✅ **Issue context saved.** Your ticket has not been submitted yet.\n\n"
            "Next, explain the actions that caused the problem and exactly what appeared.",
            ephemeral=True,
            view=ContextSavedView(),
        )


class DetailsModal(DraftModal):
    def __init__(self, draft: DraftRecord, user_id: int) -> None:
        super().__init__(title="Step 2 of 3: What Happened?", draft=draft, user_id=user_id, stage=DraftStage.DETAILS)
        data = draft.data
        try:
            category = IssueCategory(str(data.get("category", IssueCategory.OTHER)))
        except ValueError:
            category = IssueCategory.OTHER
        category_label, category_description = CATEGORY_PROMPTS[category]
        self.title_input = _text(
            custom_id=f"ktd:input:title:{draft.public_id}",
            default=data.get("title"),
            placeholder="Land claim menu closes without saving",
            min_length=12,
            max_length=100,
        )
        self.steps_input = _text(
            custom_id=f"ktd:input:steps:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("steps"),
            placeholder="1. I opened...  2. I selected...  3. I pressed...",
            min_length=60,
            max_length=1500,
        )
        self.expected_input = _text(
            custom_id=f"ktd:input:expected:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("expected"),
            placeholder="The claim should have saved and appeared in my claim list.",
            min_length=15,
            max_length=500,
        )
        self.actual_input = _text(
            custom_id=f"ktd:input:actual:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("actual"),
            placeholder="The menu closed, no confirmation appeared, and the claim was not listed.",
            min_length=35,
            max_length=1000,
        )
        self.category_detail_input = _text(
            custom_id=f"ktd:input:category-detail:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("category_detail"),
            placeholder=category_description,
            min_length=20,
            max_length=1000,
        )
        self.add_item(ui.Label(text="Useful issue title", component=self.title_input))
        self.add_item(
            ui.Label(
                text="Exact steps in order",
                description="List at least two actions. Numbered lines make the report easier to test."[:100],
                component=self.steps_input,
            )
        )
        self.add_item(ui.Label(text="Expected result", component=self.expected_input))
        self.add_item(
            ui.Label(
                text="Actual result",
                description="Describe what appeared, changed, disappeared, froze, closed, or failed."[:100],
                component=self.actual_input,
            )
        )
        self.add_item(
            ui.Label(
                text=category_label[:45],
                description=category_description[:100],
                component=self.category_detail_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = await _owned_draft(interaction, self.draft_id, self.user_id)
        if draft is None or interaction.guild is None:
            return
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        config = await bot.guild_configs.get(interaction.guild.id)
        await bot.drafts.save_stage(
            draft.id,
            DraftStage.DETAILS,
            {
                "title": self.title_input.value.strip(),
                "steps": self.steps_input.value.strip(),
                "expected": self.expected_input.value.strip(),
                "actual": self.actual_input.value.strip(),
                "category_detail": self.category_detail_input.value.strip(),
            },
            config.draft_expiry_hours,
        )
        from kingdom_tech_desk.intake.views import DetailsSavedView

        await interaction.response.send_message(
            "✅ **Problem details saved.** Your ticket has not been submitted yet.\n\n"
            "Finish with your client version, frequency, troubleshooting, and optional evidence.",
            ephemeral=True,
            view=DetailsSavedView(),
        )


class ChecksModal(DraftModal):
    def __init__(self, draft: DraftRecord, user_id: int) -> None:
        super().__init__(title="Step 3 of 3: Checks and Evidence", draft=draft, user_id=user_id, stage=DraftStage.CHECKS)
        data = draft.data
        self.frequency_input = ui.RadioGroup(
            custom_id=f"ktd:input:frequency:{draft.public_id}"[:100],
            required=True,
            options=_radio_options(FREQUENCY_OPTIONS, data.get("frequency")),
        )
        self.troubleshooting_input = ui.CheckboxGroup(
            custom_id=f"ktd:input:troubleshooting:{draft.public_id}"[:100],
            required=True,
            min_values=1,
            max_values=len(TROUBLESHOOTING_OPTIONS),
            options=_checkbox_options(TROUBLESHOOTING_OPTIONS, data.get("troubleshooting")),
        )
        self.version_input = _text(
            custom_id=f"ktd:input:version:{draft.public_id}",
            default=data.get("client_version"),
            placeholder="Example: 26.44 or 1.26.44",
            min_length=3,
            max_length=80,
        )
        self.additional_input = _text(
            custom_id=f"ktd:input:additional:{draft.public_id}",
            style=discord.TextStyle.paragraph,
            default=data.get("additional_details"),
            placeholder="Explain any other tests, or write: Nothing else attempted yet.",
            min_length=15,
            max_length=1000,
        )
        self.evidence_input = ui.FileUpload(
            custom_id=f"ktd:input:evidence:{draft.public_id}"[:100],
            required=False,
            min_values=0,
            max_values=3,
        )
        self.add_item(ui.Label(text="How often does it happen?", component=self.frequency_input))
        self.add_item(
            ui.Label(
                text="Troubleshooting attempted",
                description="Choose at least one. ‘Nothing attempted’ cannot be combined with another choice."[:100],
                component=self.troubleshooting_input,
            )
        )
        self.add_item(
            ui.Label(
                text="Minecraft client version",
                description="Use the version shown on the title screen. Explain why when it is unknown."[:100],
                component=self.version_input,
            )
        )
        self.add_item(ui.Label(text="Additional troubleshooting", component=self.additional_input))
        self.add_item(
            ui.Label(
                text="Optional screenshots or videos",
                description="Up to three files. Evidence helps, but written details are still required."[:100],
                component=self.evidence_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = await _owned_draft(interaction, self.draft_id, self.user_id)
        if draft is None or interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot: KingdomTechDeskBot = interaction.client  # type: ignore[assignment]
        config = await bot.guild_configs.get(interaction.guild.id)
        allowed, _remaining = await bot.rate_limits.hit(
            interaction.guild.id,
            interaction.user.id,
            "draft_submit",
            limit=bot.config.limits.failed_attempt_limit,
            window_seconds=bot.config.limits.failed_attempt_window_seconds,
        )
        if not allowed:
            await interaction.followup.send(
                "Too many report submissions were attempted in a short period. Your draft is saved; use Resume Draft after the rate-limit window resets.",
                ephemeral=True,
            )
            return
        updated = await bot.drafts.save_stage(
            draft.id,
            DraftStage.CHECKS,
            {
                "frequency": str(self.frequency_input.value or ""),
                "troubleshooting": [str(value) for value in self.troubleshooting_input.values],
                "client_version": self.version_input.value.strip(),
                "additional_details": self.additional_input.value.strip(),
            },
            config.draft_expiry_hours,
        )

        evidence_messages: list[str] = []
        attachments = list(self.evidence_input.values)
        if attachments:
            await bot.evidence.cleanup_draft(updated.id)
            evidence_result = await bot.evidence.save_modal_attachments(
                updated.id,
                attachments,
                min(config.evidence_limit_bytes, bot.config.limits.automatic_evidence_bytes),
            )
            evidence_messages.extend(f"⚠️ {message}" for message in evidence_result.errors)
            evidence_messages.extend(f"ℹ️ {message}" for message in evidence_result.warnings)

        await bot.drafts.increment_attempts(updated.id)
        result = bot.validator.validate(updated.data)
        updated = await bot.drafts.patch_data(
            updated.id,
            {
                "validation_score": result.score,
                "validation_errors": [
                    {"field": issue.field, "code": issue.code, "message": issue.user_message}
                    for issue in result.errors
                ],
            },
            current_stage=DraftStage.COMPLETE,
            expiry_hours=config.draft_expiry_hours,
        )
        if not result.valid:
            from kingdom_tech_desk.intake.views import FailedValidationView

            message = validation_failure_message(result)
            if evidence_messages:
                message += "\n\n" + "\n".join(evidence_messages)
            await interaction.followup.send(message[:1900], ephemeral=True, view=FailedValidationView())
            return

        updated = await bot.drafts.patch_data(
            updated.id,
            {"duplicate_matches": []},
            expiry_hours=config.draft_expiry_hours,
        )
        matches = await bot.duplicates.find_matches(
            interaction.guild.id,
            updated.data,
            bot.config.limits.similar_ticket_window_minutes,
        )
        if matches:
            from kingdom_tech_desk.intake.views import DuplicateDecisionView

            updated = await bot.drafts.patch_data(
                updated.id,
                {
                    "duplicate_matches": [
                        {
                            "kind": match.kind,
                            "id": match.id,
                            "public_id": match.public_id,
                            "title": match.title,
                            "status": match.status,
                            "score": round(match.score, 3),
                        }
                        for match in matches
                    ]
                },
                expiry_hours=config.draft_expiry_hours,
            )
            match_lines = [
                f"• **{escape_markdown(match.public_id or match.kind)}** · "
                f"{escape_markdown(match.title)} · {round(match.score * 100)}% match"
                for match in matches
            ]
            message = (
                "# Similar reports found\n"
                "Your report passed validation, but it may match an active ticket or known issue. "
                "Review these before creating a separate channel:\n\n"
                + "\n".join(match_lines)
            )
            if evidence_messages:
                message += "\n\n" + "\n".join(evidence_messages)
            await interaction.followup.send(message[:1900], ephemeral=True, view=DuplicateDecisionView())
            return

        try:
            creation = await bot.ticket_creator.create(interaction.guild, interaction.user, updated)
        except TicketCreationError as exc:
            await interaction.followup.send(f"❌ {escape_markdown(str(exc))}", ephemeral=True)
            return
        warning_text = "\n".join(evidence_messages + creation.warnings)
        response = (
            f"✅ **Technical ticket submitted:** {creation.channel.mention}\n"
            "The complete written report has been copied into the private staff channel."
        )
        if warning_text:
            response += "\n\n" + warning_text
        await interaction.followup.send(response[:1900], ephemeral=True)
