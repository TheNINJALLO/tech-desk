from __future__ import annotations

import logging

import discord
from discord.ext import commands

from kingdom_tech_desk.commands import TechCog
from kingdom_tech_desk.config import AppConfig
from kingdom_tech_desk.database import Database, run_migrations
from kingdom_tech_desk.database.repositories import (
    DraftRepository,
    GuildConfigRepository,
    IncidentRepository,
    KnownIssueRepository,
    TicketRepository,
)
from kingdom_tech_desk.intake import (
    ContextSavedView,
    DetailsSavedView,
    DuplicateDecisionView,
    FailedValidationView,
    PublicPanelView,
)
from kingdom_tech_desk.services.backups import BackupService
from kingdom_tech_desk.services.cleanup import MaintenanceService
from kingdom_tech_desk.services.duplicate_detection import DuplicateDetectionService
from kingdom_tech_desk.services.evidence import EvidenceService
from kingdom_tech_desk.services.rate_limits import RateLimitService
from kingdom_tech_desk.services.server_context import build_server_context_provider
from kingdom_tech_desk.services.severity import SeverityService
from kingdom_tech_desk.services.transcripts import TranscriptService
from kingdom_tech_desk.services.validation import ValidationService
from kingdom_tech_desk.tickets.closure import ClosureService
from kingdom_tech_desk.tickets.controls import MemberInformationView, TicketControlsView
from kingdom_tech_desk.tickets.creation import TicketCreator

LOGGER = logging.getLogger(__name__)


class KingdomTechDeskBot(commands.Bot):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.bot.command_prefix),
            intents=intents,
            description="Guided technical-support intake for The Kingdom",
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
        )
        self.config = config
        self.database = Database(config.storage.database_path)
        self.guild_configs = GuildConfigRepository(self.database)
        self.drafts = DraftRepository(self.database)
        self.tickets = TicketRepository(self.database)
        self.known_issues = KnownIssueRepository(self.database)
        self.incidents = IncidentRepository(self.database)

        self.validator = ValidationService(
            config.validation.vague_phrases,
            config.validation.minimum_combined_words,
        )
        self.rate_limits = RateLimitService(self.database)
        self.evidence = EvidenceService(
            config.storage.evidence_dir,
            self.drafts,
            max_files=config.limits.max_evidence_files,
        )
        self.duplicates = DuplicateDetectionService(self.tickets, self.known_issues)
        self.severity = SeverityService()
        self.server_context = build_server_context_provider(config.server_context)
        self.transcripts = TranscriptService(config.storage.transcript_dir)
        self.backups = BackupService(
            self.database,
            config.storage.backup_dir,
            config.storage.backup_retention,
        )
        self.closure = ClosureService(self, self.tickets, self.guild_configs, self.transcripts)
        self.ticket_creator = TicketCreator(
            self,
            self.drafts,
            self.tickets,
            self.guild_configs,
            self.evidence,
            self.severity,
            self.duplicates,
            self.server_context,
        )
        self.maintenance = MaintenanceService(self)
        self._startup_reconciled = False

    async def setup_hook(self) -> None:
        await self.database.connect()
        await run_migrations(self.database)

        # Every public and ticket control has timeout=None and a stable custom_id.
        # Registering these views makes old messages interactive after a process restart.
        self.add_view(PublicPanelView())
        self.add_view(ContextSavedView())
        self.add_view(DetailsSavedView())
        self.add_view(FailedValidationView())
        self.add_view(DuplicateDecisionView())
        self.add_view(TicketControlsView())
        self.add_view(MemberInformationView())

        await self.add_cog(TechCog(self))
        if self.config.bot.sync_commands_on_start:
            if self.config.bot.development_guild_id:
                guild = discord.Object(id=self.config.bot.development_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                LOGGER.info("Synced %s app commands to development guild %s", len(synced), guild.id)
            else:
                synced = await self.tree.sync()
                LOGGER.info("Synced %s global app commands", len(synced))
        self.maintenance.start()

    async def on_ready(self) -> None:
        if self.user is None:
            return
        LOGGER.info("Logged in as %s (%s) in %s guild(s)", self.user, self.user.id, len(self.guilds))
        activity = discord.Activity(type=discord.ActivityType.watching, name=self.config.bot.status_text)
        await self.change_presence(status=discord.Status.online, activity=activity)
        if not self._startup_reconciled:
            result = await self.maintenance.reconcile_startup()
            LOGGER.info("Startup reconciliation: %s", result)
            self._startup_reconciled = True

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.guild_configs.ensure(guild.id)

    async def on_command_error(self, context: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        LOGGER.error("Prefix command failed", exc_info=error)

    async def close(self) -> None:
        await self.maintenance.stop()
        await self.server_context.close()
        try:
            await super().close()
        finally:
            await self.database.close()
