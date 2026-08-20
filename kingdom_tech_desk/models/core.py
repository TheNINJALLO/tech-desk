from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any


class DraftStage(IntEnum):
    CONTEXT = 1
    DETAILS = 2
    CHECKS = 3
    COMPLETE = 4


class DraftStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    INVESTIGATING = "INVESTIGATING"
    WAITING_ON_MEMBER = "WAITING_ON_MEMBER"
    FIX_PENDING = "FIX_PENDING"
    KNOWN_ISSUE = "KNOWN_ISSUE"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CREATION_FAILED = "CREATION_FAILED"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class ResolutionType(StrEnum):
    FIXED = "FIXED"
    WORKAROUND_PROVIDED = "WORKAROUND_PROVIDED"
    KNOWN_ISSUE = "KNOWN_ISSUE"
    DUPLICATE = "DUPLICATE"
    USER_ERROR = "USER_ERROR"
    UNABLE_TO_REPRODUCE = "UNABLE_TO_REPRODUCE"
    NO_RESPONSE = "NO_RESPONSE"
    NOT_A_TECHNICAL_ISSUE = "NOT_A_TECHNICAL_ISSUE"
    OTHER = "OTHER"


class IssueCategory(StrEnum):
    JOIN_DISCONNECT = "join_disconnect"
    CRASH = "crash"
    RESOURCE_PACK = "resource_pack"
    COMMAND_ADDON = "command_addon"
    LAG_DESYNC = "lag_desync"
    INVENTORY_LOSS = "inventory_loss"
    SHOP_ECONOMY_CLAIM = "shop_economy_claim"
    PROXY_TRANSFER = "proxy_transfer"
    VISUAL = "visual"
    OTHER = "other"


ISSUE_CATEGORY_LABELS: dict[str, str] = {
    IssueCategory.JOIN_DISCONNECT: "Unable to join or disconnected",
    IssueCategory.CRASH: "Minecraft crashed or closed",
    IssueCategory.RESOURCE_PACK: "Resource pack or texture",
    IssueCategory.COMMAND_ADDON: "Command, menu, addon, or plugin",
    IssueCategory.LAG_DESYNC: "Lag, desync, or block rollback",
    IssueCategory.INVENTORY_LOSS: "Inventory or item loss",
    IssueCategory.SHOP_ECONOMY_CLAIM: "Shop, economy, or land claim",
    IssueCategory.PROXY_TRANSFER: "Hub, proxy, or transfer",
    IssueCategory.VISUAL: "Visual or cosmetic",
    IssueCategory.OTHER: "Other",
}


@dataclass(slots=True)
class ValidationIssue:
    field: str
    code: str
    user_message: str
    staff_message: str
    remediation_stage: DraftStage


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    score: int = 0
    normalized_fields: dict[str, Any] = field(default_factory=dict)
    failed_stage: DraftStage | None = None


@dataclass(slots=True)
class DraftRecord:
    id: int
    public_id: str
    guild_id: int
    user_id: int
    status: DraftStatus
    current_stage: DraftStage
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    submission_attempts: int = 0


@dataclass(slots=True)
class EvidenceRecord:
    id: int | None
    draft_id: int
    safe_name: str
    original_name: str
    path: Path | None
    content_type: str | None
    size: int
    media_kind: str | None
    requires_direct_upload: bool = False
    created_at: datetime | None = None


@dataclass(slots=True)
class TicketRecord:
    id: int
    guild_id: int
    ticket_number: int
    public_id: str
    draft_id: int | None
    reporter_id: int
    channel_id: int | None
    status: TicketStatus
    severity: Severity
    assignee_id: int | None
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    closure_reason: str | None = None
    resolution_type: str | None = None
    user_resolution: str | None = None
    internal_note: str | None = None
    delete_after: datetime | None = None


@dataclass(slots=True)
class DuplicateMatch:
    kind: str
    id: int
    title: str
    score: float
    status: str
    public_id: str | None = None


@dataclass(slots=True)
class ServerSnapshot:
    available: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class GuildConfig:
    guild_id: int
    support_role_id: int | None = None
    escalation_role_ids: list[int] = field(default_factory=list)
    open_category_id: int | None = None
    closed_category_id: int | None = None
    panel_channel_id: int | None = None
    panel_message_id: int | None = None
    log_channel_id: int | None = None
    incident_channel_id: int | None = None
    server_name: str = "The Kingdom"
    server_version: str = "Unknown"
    draft_expiry_hours: int = 24
    max_open_tickets: int = 3
    evidence_limit_bytes: int = 20 * 1024 * 1024
    waiting_reminder_hours: int = 24
    waiting_second_reminder_hours: int = 48
    waiting_auto_close_hours: int = 72
    closed_retention_hours: int = 72


@dataclass(slots=True)
class InformationRequest:
    id: int
    ticket_id: int
    requested_by: int
    requested_fields: list[str]
    custom_question: str | None
    response: str | None
    status: str
    created_at: datetime
    responded_at: datetime | None = None
