from __future__ import annotations

from typing import Any

import discord

from kingdom_tech_desk.models.core import (
    ISSUE_CATEGORY_LABELS,
    DraftRecord,
    ValidationIssue,
    ValidationResult,
)
from kingdom_tech_desk.services.security import escape_markdown

PLATFORM_LABELS = {
    "windows": "Windows",
    "xbox": "Xbox",
    "playstation": "PlayStation",
    "switch": "Nintendo Switch",
    "android": "Android",
    "ios": "iPhone or iPad",
    "other": "Other",
}
SCOPE_LABELS = {
    "only_me": "Only me",
    "several": "Several players",
    "everyone": "Everyone",
}
FREQUENCY_LABELS = {
    "once": "Happened once",
    "every_time": "Happens every time",
    "sometimes": "Happens sometimes",
    "cannot_reproduce": "Cannot reproduce yet",
}
TROUBLESHOOTING_LABELS = {
    "rejoined_server": "Rejoined the server",
    "restarted_minecraft": "Restarted Minecraft",
    "restarted_device": "Restarted the device",
    "retried_action": "Tried the action again",
    "checked_connection": "Checked the internet connection",
    "another_player_tested": "Another player tested it",
    "nothing_attempted": "Nothing attempted yet",
}


def display_value(field: str, value: Any) -> str:
    if field == "category":
        return ISSUE_CATEGORY_LABELS.get(str(value), str(value))
    if field == "platform":
        return PLATFORM_LABELS.get(str(value), str(value))
    if field == "affected_scope":
        return SCOPE_LABELS.get(str(value), str(value))
    if field == "frequency":
        return FREQUENCY_LABELS.get(str(value), str(value))
    if field == "troubleshooting" and isinstance(value, list):
        return "\n".join(f"• {TROUBLESHOOTING_LABELS.get(str(item), str(item))}" for item in value)
    return str(value or "Not supplied")


def _safe_field(
    embed: discord.Embed, title: str, value: Any, *, inline: bool = False, limit: int = 500
) -> None:
    text = escape_markdown(display_value(title.lower().replace(" ", "_"), value))
    limit = max(50, min(1024, limit))
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    embed.add_field(name=title[:256], value=text or "Not supplied", inline=inline)


def draft_review_embed(draft: DraftRecord) -> discord.Embed:
    data = draft.data
    embed = discord.Embed(
        title=f"Technical report draft · {draft.public_id}",
        description=(
            "This is the information currently saved. The private staff ticket does not exist until "
            "the report passes validation."
        ),
        colour=discord.Colour.blurple(),
        timestamp=draft.updated_at,
    )
    _safe_field(embed, "Category", display_value("category", data.get("category")), inline=True)
    _safe_field(embed, "Platform", display_value("platform", data.get("platform")), inline=True)
    _safe_field(embed, "Affected scope", display_value("affected_scope", data.get("affected_scope")), inline=True)
    _safe_field(embed, "Gamertag", data.get("gamertag"), inline=True)
    _safe_field(embed, "Client version", data.get("client_version"), inline=True)
    _safe_field(embed, "Frequency", display_value("frequency", data.get("frequency")), inline=True)
    _safe_field(embed, "Where and when", data.get("where_when"))
    _safe_field(embed, "Title", data.get("title"))
    _safe_field(embed, "Exact steps", data.get("steps"))
    _safe_field(embed, "Expected result", data.get("expected"))
    _safe_field(embed, "Actual result", data.get("actual"))
    _safe_field(embed, "Category-specific details", data.get("category_detail"))
    _safe_field(embed, "Troubleshooting", display_value("troubleshooting", data.get("troubleshooting", [])))
    _safe_field(embed, "Additional details", data.get("additional_details"))
    embed.set_footer(text=f"Stage {int(draft.current_stage)} · Draft expires {draft.expires_at:%Y-%m-%d %H:%M UTC}")
    return embed


def validation_failure_message(result: ValidationResult) -> str:
    lines = [
        "# ❌ YOUR TECHNICAL TICKET WAS NOT SUBMITTED",
        "",
        "Your report is saved, but these items must be corrected:",
    ]
    for issue in result.errors[:12]:
        label = issue.field.replace("_", " ").title()
        lines.append(f"\n**{label}**\n{issue.user_message}")
    if len(result.errors) > 12:
        lines.append(f"\nPlus {len(result.errors) - 12} additional validation issue(s).")
    lines.extend(
        [
            "",
            "Your current answers remain saved for 24 hours by default. You do not need to start over.",
            "Use **Fix Missing Details** to reopen the earliest section that needs attention.",
        ]
    )
    return "\n".join(lines)[:4000]


def validation_issue_summary(issues: list[ValidationIssue]) -> str:
    return "\n".join(
        f"• **{issue.field.replace('_', ' ').title()}**: {issue.user_message}" for issue in issues[:8]
    )[:1900]


def known_issues_embed(issues: list[dict[str, Any]]) -> discord.Embed:
    embed = discord.Embed(
        title="The Kingdom · Active Known Issues",
        colour=discord.Colour.gold(),
    )
    if not issues:
        embed.description = "No public known issues are currently listed."
        return embed
    embed.description = "Check these before submitting a separate report. Internal staff notes are never shown here."
    for issue in issues[:10]:
        value_parts = [f"Category: `{escape_markdown(str(issue['category']))}`"]
        if issue.get("workaround"):
            value_parts.append(f"Workaround: {escape_markdown(str(issue['workaround']))}")
        platforms = issue.get("platforms") or []
        if platforms:
            value_parts.append("Platforms: " + ", ".join(escape_markdown(str(item)) for item in platforms))
        embed.add_field(
            name=f"{issue['public_id']} · {escape_markdown(str(issue['public_title']))}"[:256],
            value="\n".join(value_parts)[:1024],
            inline=False,
        )
    if len(issues) > 10:
        embed.set_footer(text=f"Showing 10 of {len(issues)} active issues")
    return embed
