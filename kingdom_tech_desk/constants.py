from __future__ import annotations

from kingdom_tech_desk.models.core import DraftStage, IssueCategory

PANEL_START_CUSTOM_ID = "ktd:panel:start:v1"
PANEL_RESUME_CUSTOM_ID = "ktd:panel:resume:v1"
PANEL_KNOWN_CUSTOM_ID = "ktd:panel:known:v1"

DRAFT_CONTINUE_DETAILS_ID = "ktd:draft:continue:details:v1"
DRAFT_CONTINUE_CHECKS_ID = "ktd:draft:continue:checks:v1"
DRAFT_FIX_ID = "ktd:draft:fix:v1"
DRAFT_REVIEW_DETAILS_ID = "ktd:draft:review:details:v1"
DRAFT_REVIEW_FAILED_ID = "ktd:draft:review:failed:v1"
DRAFT_CANCEL_CONTEXT_ID = "ktd:draft:cancel:context:v1"
DRAFT_CANCEL_DETAILS_ID = "ktd:draft:cancel:details:v1"
DRAFT_CANCEL_FAILED_ID = "ktd:draft:cancel:failed:v1"
DRAFT_CANCEL_DUPLICATE_ID = "ktd:draft:cancel:duplicate:v1"
DRAFT_SUBMIT_ANYWAY_ID = "ktd:draft:submit-anyway:v1"
DRAFT_SUBSCRIBE_MATCH_ID = "ktd:draft:subscribe-match:v1"
DRAFT_VIEW_MATCHES_ID = "ktd:draft:view-matches:v1"

TICKET_CLAIM_ID = "ktd:ticket:claim:v1"
TICKET_UNCLAIM_ID = "ktd:ticket:unclaim:v1"
TICKET_REQUEST_INFO_ID = "ktd:ticket:request-info:v1"
TICKET_STATUS_ID = "ktd:ticket:status:v1"
TICKET_SEVERITY_ID = "ktd:ticket:severity:v1"
TICKET_ADD_MEMBER_ID = "ktd:ticket:add-member:v1"
TICKET_REMOVE_MEMBER_ID = "ktd:ticket:remove-member:v1"
TICKET_ESCALATE_ID = "ktd:ticket:escalate:v1"
TICKET_INCIDENT_ID = "ktd:ticket:incident:v1"
TICKET_DUPLICATE_ID = "ktd:ticket:duplicate:v1"
TICKET_RESOLVE_ID = "ktd:ticket:resolve:v1"
TICKET_CLOSE_ID = "ktd:ticket:close:v1"
MEMBER_INFO_RESPONSE_ID = "ktd:ticket:member-info:v1"

ISSUE_OPTIONS: list[tuple[str, str]] = [
    ("Unable to join or disconnected", IssueCategory.JOIN_DISCONNECT),
    ("Minecraft crashed or closed", IssueCategory.CRASH),
    ("Resource pack or texture", IssueCategory.RESOURCE_PACK),
    ("Command, menu, addon, or plugin", IssueCategory.COMMAND_ADDON),
    ("Lag, desync, or block rollback", IssueCategory.LAG_DESYNC),
    ("Inventory or item loss", IssueCategory.INVENTORY_LOSS),
    ("Shop, economy, or land claim", IssueCategory.SHOP_ECONOMY_CLAIM),
    ("Hub, proxy, or transfer", IssueCategory.PROXY_TRANSFER),
    ("Visual or cosmetic", IssueCategory.VISUAL),
    ("Other", IssueCategory.OTHER),
]

PLATFORM_OPTIONS = [
    ("Windows", "windows"),
    ("Xbox", "xbox"),
    ("PlayStation", "playstation"),
    ("Nintendo Switch", "switch"),
    ("Android", "android"),
    ("iPhone or iPad", "ios"),
    ("Other", "other"),
]

AFFECTED_OPTIONS = [
    ("Only me", "only_me"),
    ("Several players", "several"),
    ("Everyone", "everyone"),
]

FREQUENCY_OPTIONS = [
    ("Happened once", "once"),
    ("Happens every time", "every_time"),
    ("Happens sometimes", "sometimes"),
    ("Cannot reproduce yet", "cannot_reproduce"),
]

TROUBLESHOOTING_OPTIONS = [
    ("Rejoined the server", "rejoined_server"),
    ("Restarted Minecraft", "restarted_minecraft"),
    ("Restarted the device", "restarted_device"),
    ("Tried the action again", "retried_action"),
    ("Checked the internet connection", "checked_connection"),
    ("Another player tested it", "another_player_tested"),
    ("Nothing attempted yet", "nothing_attempted"),
]

CATEGORY_PROMPTS = {
    IssueCategory.JOIN_DISCONNECT: (
        "Connection details",
        "Enter the exact disconnect message and what happened when you retried.",
    ),
    IssueCategory.CRASH: (
        "Crash details",
        "Describe the last action before Minecraft closed and where the game returned.",
    ),
    IssueCategory.RESOURCE_PACK: (
        "Resource-pack details",
        "Enter the pack name and whether it failed during download, import, load, or join.",
    ),
    IssueCategory.COMMAND_ADDON: (
        "Feature details",
        "Enter the exact command, item, block, menu, button, or feature used.",
    ),
    IssueCategory.LAG_DESYNC: (
        "Lag or rollback details",
        "Enter the area, delayed action, rollback behavior, and whether others saw it.",
    ),
    IssueCategory.INVENTORY_LOSS: (
        "Lost-item details",
        "Enter the item, quantity, container, and action immediately before the loss.",
    ),
    IssueCategory.SHOP_ECONOMY_CLAIM: (
        "Transaction or claim details",
        "Enter the item, amount, balance, transaction, claim, or command involved.",
    ),
    IssueCategory.PROXY_TRANSFER: (
        "Transfer details",
        "Enter the source server, destination server, and where the transfer stopped.",
    ),
    IssueCategory.VISUAL: (
        "Visual details",
        "Describe what looked incorrect and exactly where it appeared.",
    ),
    IssueCategory.OTHER: (
        "Technical identifiers",
        "Provide names or identifiers that let staff locate the affected system.",
    ),
}

FIELD_STAGES: dict[str, DraftStage] = {
    "category": DraftStage.CONTEXT,
    "platform": DraftStage.CONTEXT,
    "affected_scope": DraftStage.CONTEXT,
    "gamertag": DraftStage.CONTEXT,
    "where_when": DraftStage.CONTEXT,
    "title": DraftStage.DETAILS,
    "steps": DraftStage.DETAILS,
    "expected": DraftStage.DETAILS,
    "actual": DraftStage.DETAILS,
    "category_detail": DraftStage.DETAILS,
    "frequency": DraftStage.CHECKS,
    "troubleshooting": DraftStage.CHECKS,
    "client_version": DraftStage.CHECKS,
    "additional_details": DraftStage.CHECKS,
}

DEFAULT_VAGUE_PHRASES = [
    "doesn't work",
    "does not work",
    "not working",
    "broken",
    "fix it",
    "help",
    "nothing",
    "it kicked me",
    "got kicked",
    "it crashed",
    "watch the video",
    "watch this",
    "idk",
    "i don't know",
    "no idea",
    "same as above",
    "same",
    "bugged",
]

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
