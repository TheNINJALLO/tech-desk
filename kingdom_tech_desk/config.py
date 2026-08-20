from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kingdom_tech_desk.constants import DEFAULT_VAGUE_PHRASES


@dataclass(slots=True)
class BotSettings:
    name: str = "Kingdom Tech Desk"
    command_prefix: str = "!ktd"
    status_text: str = "Technical reports"
    sync_commands_on_start: bool = True
    development_guild_id: int | None = None


@dataclass(slots=True)
class StorageSettings:
    database_path: Path = Path("data/kingdom_tech_desk.db")
    evidence_dir: Path = Path("data/evidence")
    transcript_dir: Path = Path("data/transcripts")
    backup_dir: Path = Path("data/backups")
    log_dir: Path = Path("logs")
    backup_retention: int = 14


@dataclass(slots=True)
class LimitSettings:
    draft_expiry_hours: int = 24
    max_open_tickets_per_member: int = 3
    max_evidence_files: int = 3
    automatic_evidence_bytes: int = 20 * 1024 * 1024
    failed_attempt_window_seconds: int = 600
    failed_attempt_limit: int = 8
    similar_ticket_window_minutes: int = 30
    possible_incident_threshold: int = 3


@dataclass(slots=True)
class LifecycleSettings:
    first_waiting_reminder_hours: int = 24
    second_waiting_reminder_hours: int = 48
    auto_close_waiting_hours: int = 72
    closed_channel_retention_hours: int = 72


@dataclass(slots=True)
class ValidationSettings:
    minimum_combined_words: int = 45
    vague_phrases: list[str] = field(default_factory=lambda: list(DEFAULT_VAGUE_PHRASES))


@dataclass(slots=True)
class ServerContextSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    authentication_token: str = ""
    timeout_seconds: float = 3.0
    verify_tls: bool = True
    server_mapping: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AppConfig:
    token: str
    owner_ids: set[int]
    bot: BotSettings = field(default_factory=BotSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    limits: LimitSettings = field(default_factory=LimitSettings)
    lifecycle: LifecycleSettings = field(default_factory=LifecycleSettings)
    validation: ValidationSettings = field(default_factory=ValidationSettings)
    server_context: ServerContextSettings = field(default_factory=ServerContextSettings)
    config_path: Path = Path("config.yaml")

    def ensure_directories(self) -> None:
        self.storage.database_path.parent.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.storage.evidence_dir,
            self.storage.transcript_dir,
            self.storage.backup_dir,
            self.storage.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _as_int_or_none(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name, {})
    return value if isinstance(value, dict) else {}


def _path(value: Any, default: Path) -> Path:
    return Path(str(value)) if value not in (None, "") else default


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("KTD_CONFIG", "config.yaml"))
    payload: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required. Copy .env.example or set it in the panel variables.")

    owner_ids = {
        int(value.strip())
        for value in os.getenv("KTD_OWNER_IDS", "").split(",")
        if value.strip().isdigit()
    }

    bot_data = _section(payload, "bot")
    storage_data = _section(payload, "storage")
    limit_data = _section(payload, "limits")
    lifecycle_data = _section(payload, "lifecycle")
    validation_data = _section(payload, "validation")
    server_data = _section(payload, "server_context")

    env_dev_guild = os.getenv("KTD_DEV_GUILD_ID", "").strip()
    development_guild = _as_int_or_none(env_dev_guild or bot_data.get("development_guild_id"))

    config = AppConfig(
        token=token,
        owner_ids=owner_ids,
        config_path=config_path,
        bot=BotSettings(
            name=str(bot_data.get("name", "Kingdom Tech Desk")),
            command_prefix=str(bot_data.get("command_prefix", "!ktd")),
            status_text=str(bot_data.get("status_text", "Technical reports")),
            sync_commands_on_start=bool(bot_data.get("sync_commands_on_start", True)),
            development_guild_id=development_guild,
        ),
        storage=StorageSettings(
            database_path=_path(storage_data.get("database_path"), Path("data/kingdom_tech_desk.db")),
            evidence_dir=_path(storage_data.get("evidence_dir"), Path("data/evidence")),
            transcript_dir=_path(storage_data.get("transcript_dir"), Path("data/transcripts")),
            backup_dir=_path(storage_data.get("backup_dir"), Path("data/backups")),
            log_dir=_path(storage_data.get("log_dir"), Path("logs")),
            backup_retention=int(storage_data.get("backup_retention", 14)),
        ),
        limits=LimitSettings(
            draft_expiry_hours=int(limit_data.get("draft_expiry_hours", 24)),
            max_open_tickets_per_member=int(limit_data.get("max_open_tickets_per_member", 3)),
            max_evidence_files=int(limit_data.get("max_evidence_files", 3)),
            automatic_evidence_bytes=int(limit_data.get("automatic_evidence_bytes", 20 * 1024 * 1024)),
            failed_attempt_window_seconds=int(limit_data.get("failed_attempt_window_seconds", 600)),
            failed_attempt_limit=int(limit_data.get("failed_attempt_limit", 8)),
            similar_ticket_window_minutes=int(limit_data.get("similar_ticket_window_minutes", 30)),
            possible_incident_threshold=int(limit_data.get("possible_incident_threshold", 3)),
        ),
        lifecycle=LifecycleSettings(
            first_waiting_reminder_hours=int(lifecycle_data.get("first_waiting_reminder_hours", 24)),
            second_waiting_reminder_hours=int(lifecycle_data.get("second_waiting_reminder_hours", 48)),
            auto_close_waiting_hours=int(lifecycle_data.get("auto_close_waiting_hours", 72)),
            closed_channel_retention_hours=int(lifecycle_data.get("closed_channel_retention_hours", 72)),
        ),
        validation=ValidationSettings(
            minimum_combined_words=int(validation_data.get("minimum_combined_words", 45)),
            vague_phrases=[
                str(item).strip().lower()
                for item in validation_data.get("vague_phrases", DEFAULT_VAGUE_PHRASES)
                if str(item).strip()
            ],
        ),
        server_context=ServerContextSettings(
            enabled=bool(server_data.get("enabled", False)),
            base_url=str(server_data.get("base_url", "http://127.0.0.1:8080")).rstrip("/"),
            authentication_token=str(server_data.get("authentication_token", "")),
            timeout_seconds=float(server_data.get("timeout_seconds", 3)),
            verify_tls=bool(server_data.get("verify_tls", True)),
            server_mapping={str(k): str(v) for k, v in server_data.get("server_mapping", {}).items()},
        ),
    )
    config.ensure_directories()
    return config
